"""Benchmark the checkout's tool_view: model request → discovery → synthetic tool → final answer.

    PYTHONPATH=. .venv/bin/python -B scripts/benchmark_tool_search.py         # offline, no key
    PYTHONPATH=. .venv/bin/python -B scripts/benchmark_tool_search.py --live  # only after freeze confirmation

Live uses only the configured OpenCode Go apiKey from ~/.nanobot/config.json and the fixed official
endpoint/model below. No SDK retries, redirects, proxies, provider fallback, plugin loading, real
files/commands or MCP services. Private reports: tmp/tool-search-eval/<run>/ inside this checkout.
The total HTTP cap includes model preflight, rejected requests and both real cache arms. A catalog
limit on the first eager request permits one predefined smaller comparison; other errors stop.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean

import httpx

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.tool_search import tool_view
from nanobot.agent.tools.tool_search_index import ToolSearchIndex
from nanobot.config.schema import ToolsConfig

MODEL = "deepseek-v4.1-flash"
BASE = "https://opencode.ai/zen/go/v1"
LIMIT = 65
TIMEOUT = 50
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'tmp/tool-search-eval'
SYSTEM = ("Answer the user's request. For records, files and changes use the appropriate tool and "
          "report the exact value returned; do not guess. For general questions answer directly. Be concise.")
LIMITATIONS = (
    'Single synthetic sample per case/arm, not a production distribution or a confidence interval.',
    'Real Go model/tool-call round trips and checkout registry/view, not the whole agent loop, provider adapter, '
    'MCP transport, Python entry-point loader or real file/shell/business tools.',
    'Exact-name offline reachability is not natural-language recall. Live recall@5 uses only the first actual '
    'search reply across all required non-core names (no search = miss). Multi-step search may recover later.',
    'Clean means exact ordered non-search calls and arguments without errors; direct cases must not search. '
    'Completion permits recovery on lookup cases but requires ordered successful calls and final fixture value.',
    'KV evidence is provider-reported token accounting, not internal cache inspection. Same session/messages, '
    'search arm first, no cache flush, no guaranteed cold start, routing, serialization or cache isolation. '
    'Missing counters are null, never inferred from latency or local token estimates.',
    'Budget 1 forces discovery; the local catalog-size estimate is ceil(compact non-core schema UTF-8 bytes / 3). '
    'Reported chat token counts come only from Go.',
)

# 12 adjacent services x 25 operations. Sister services share the same operations; other services
# also share 20 generic facets. A smaller comparison preserves every sister service and target.
DOMAINS = (
    ((('payables', 'supplier invoices and vendor bills payable'),
      ('receivables', 'customer invoices and trade bills receivable')),
     ('unpaid_balance:remaining amount outstanding', 'due_date:payment deadline',
      'shipment_link:linked inbound freight reference', 'tax_total:invoice taxes', 'terms:payment terms')),
    ((('inbound', 'incoming freight deliveries received from suppliers'),
      ('outbound', 'outgoing freight deliveries dispatched to customers')),
     ('proof_of_delivery:handover receipt code', 'arrival:estimated time of arrival',
      'carrier:shipment transport company', 'waybill:consignment note', 'depot:freight depot')),
    ((('warehouse', 'distribution warehouse inventory and stock'), ('storefront', 'retail shop inventory and stock')),
     ('available_units:free quantity not reserved', 'reserved_units:quantity committed to orders',
      'on_hand:total physical quantity', 'reorder_level:restocking threshold', 'bin:storage slot')),
    ((('employeeclaims', 'staff travel reimbursement and expense claims'),
      ('buyerclaims', 'customer purchase refund and expense claims')),
     ('payout_date:date money was paid out', 'payout_amount:money reimbursed',
      'policy:applicable claim rules', 'approval:approval decision', 'receipt:expense receipt')),
    ((('helpdesk', 'internal staff support tickets'), ('care', 'external customer support tickets')),
     ('queue:triage queue', 'priority:urgency', 'sla:response deadline', 'category:issue class', 'closure:resolution')),
    ((('vendorcheck', 'supplier compliance reviews'), ('clientcheck', 'customer compliance reviews')),
     ('rating:risk grade', 'evidence:audit evidence', 'expiry:review expiration date',
      'checklist:review controls', 'decision:review outcome')),
)
COMMON = ("owner", "status", "summary", "updated_at", "created_at", "region", "currency", "notes", "tags",
          "history", "source", "reference", "version", "department", "cost_center", "reviewer", "contact",
          "attachments", "classification", "retention")


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def value(name, ref):
    prefix = 'FRT' if name.endswith('_shipment_link') else 'VAL'
    return prefix + '-' + digest(f'{name}/{ref}')[:10].upper()


# Ordinary Python Tool instances, with no transport prefix or MCP metadata, stand in for plugins.
PLUGIN_SERVICES = {'receivables', 'inbound', 'warehouse', 'employeeclaims', 'care', 'clientcheck'}


class PluginLookup(Tool):
    read_only = True

    def __init__(self, server, scope, facet):
        self.server = server
        field, _, meaning = facet.partition(':')
        self._name = f'{server}_{field}'
        self._description = f'Read {meaning or field.replace("_", " ")} for {scope} by record identifier.'

    @property
    def name(self):
        return self._name

    @property
    def description(self):
        return self._description

    @property
    def parameters(self):
        return {"type": "object", "properties": {"ref": {"type": "string", "description": "Exact record identifier"}},
                "required": ["ref"], "additionalProperties": False}

    async def execute(self, ref):
        return value(self.name, ref)


class McpLookup(PluginLookup):
    @property
    def mcp_server(self):
        return self.server

    @property
    def name(self):
        return 'mcp_' + self._name


# Deliberately independent of the product allowlist. Never instantiate a real core tool.
CORE = {
    'read_file': ('Read a text file by path.', ('path',)),
    'edit_file': ('Replace exact text in a file; return the edit receipt.', ('path', 'old_text', 'new_text')),
    'write_file': ('Write text to a file.', ('path', 'content')),
    'apply_patch': ('Apply a text patch.', ('patch',)),
    'exec': ('Run a command.', ('command',)),
    'exec_session': ('Poll a running command.', ('session_id',)),
    'list_exec_sessions': ('List running commands.', ()),
}
SEARCH = 'tool_search'
READ_PATH, EDIT_PATH = 'notes/release-id.txt', 'notes/banner.txt'


class CoreSample(Tool):
    def __init__(self, name, files):
        self._name, self.files = name, files

    @property
    def name(self):
        return self._name

    @property
    def description(self):
        return CORE[self.name][0]

    @property
    def parameters(self):
        fields = CORE[self.name][1]
        return {'type': 'object', 'properties': {k: {'type': 'string'} for k in fields},
                'required': list(fields), 'additionalProperties': False}

    async def execute(self, **args):
        path = args.get('path')
        if self.name == 'read_file' and path in self.files:
            return self.files[path]
        if self.name == 'edit_file' and path == EDIT_PATH and args['old_text'] == self.files[path]:
            self.files[path] = args['new_text']
            return value(self.name, path)
        if self.name == 'exec' and args['command'] == 'printf READY':
            return 'READY'  # Literal in memory, not a shell.
        return self.error('Not available in the synthetic fixture.')


def catalog(n, *, plugin_only=False):
    registry = ToolRegistry()
    for services, specific in DOMAINS:
        for server, scope in services:
            cls = PluginLookup if plugin_only or server in PLUGIN_SERVICES else McpLookup
            for facet in (*specific, *COMMON)[:n // 12]:
                registry.register(cls(server, scope, facet))
    assert len(registry.tool_names) == n
    if not plugin_only:
        files = {READ_PATH: value('read_file', READ_PATH), EDIT_PATH: 'DRAFT'}
        for name in CORE:
            registry.register(CoreSample(name, files))
    return registry


@dataclass(frozen=True)
class Case:
    id: str
    prompt: str
    steps: tuple = ()  # ordered (registered name, exact ref); second ref comes only from first result

    @property
    def answer(self):
        return value(*self.steps[-1]) if self.steps else '42'


def step_args(name, ref):
    if name == 'edit_file':
        return {'path': ref, 'old_text': 'DRAFT', 'new_text': 'APPROVED'}
    return {'path' if name == 'read_file' else 'ref': ref}


LINK = 'mcp_payables_shipment_link'
CASES = (
    Case('en_balance', 'What is the unpaid balance on supplier invoice V-410?',
         (('mcp_payables_unpaid_balance', 'V-410'),)),
    Case('zh_units', '配送仓库的 SKU-82 现在还有多少件可以分配给新订单？不要给我包含已锁定库存的总数。',
         (('warehouse_available_units', 'SKU-82'),)),
    Case('en_paraphrase', 'An employee says their trip expenses finally landed in their bank account. '
         'For claim E-73, when did the money go out?', (('employeeclaims_payout_date', 'E-73'),)),
    Case('zh_handover', '想确认客户签收了我们发出的那批货，麻烦查一下运单 O-38 的交接回执编号。',
         (('mcp_outbound_proof_of_delivery', 'O-38'),)),
    Case('en_chain', 'Start with vendor bill B-990. Find its linked incoming shipment, then give me the '
         'handover receipt code for that shipment.', ((LINK, 'B-990'),
                                                      ('inbound_proof_of_delivery', value(LINK, 'B-990')))),
    Case('zh_plain', '把六乘七的结果用阿拉伯数字写出来，只给数字。'),
    Case('zh_read', '麻烦看一下 notes/release-id.txt，把文件里的发布编号发我。', (('read_file', READ_PATH),)),
    Case('en_edit', 'In notes/banner.txt replace DRAFT with APPROVED. Send me the edit receipt.',
         (('edit_file', EDIT_PATH),)),
)


class BenchmarkError(Exception):
    pass


class CatalogLimitError(BenchmarkError):
    pass


def usage_counts(u):
    details = u.get('prompt_tokens_details') or {}
    cached = details.get('cached_tokens')
    if cached is None:
        cached = u.get('prompt_cache_hit_tokens', u.get('cached_tokens'))
    return {'prompt': u.get('prompt_tokens'), 'completion': u.get('completion_tokens'),
            'cached': cached, 'miss': u.get('prompt_cache_miss_tokens')}


def numeric_tree(obj):
    """Keep provider usage evidence, not response headers, billing IDs or arbitrary string fields."""
    return {k: numeric_tree(v) if isinstance(v, dict) else v for k, v in obj.items()
            if isinstance(v, (int, float, dict)) or v is None}


class Run:
    def __init__(self, http, key, dest, max_requests):
        self.http, self._key, self.dest = http, key, dest
        self.max_requests = max_requests
        self.count = 0
        self.cases = []
        self.cache = []
        self.errors = []

    def save(self, name, data, append=False):
        # Defense in depth: never persist the credential, even if a provider echoed it in an error.
        text = json.dumps(data, ensure_ascii=False, indent=None if append else 2).replace(self._key, '[redacted]')
        with (self.dest / name).open('a' if append else 'w', encoding='utf8') as f:
            f.write(text + '\n')

    async def request(self, label, session, body=None):
        if self.count >= self.max_requests:
            raise BenchmarkError('HTTP request budget exhausted')
        self.count += 1
        meta = dict(seq=self.count, label=label, session=session)
        if body is not None:
            meta.update(tool_count=len(body['tools']), payload_sha256=digest(json.dumps(body)),
                        schemas_sha256=digest(json.dumps(body['tools'])), messages_sha256=digest(json.dumps(body['messages'])))
        start = time.monotonic()
        try:
            async with asyncio.timeout(TIMEOUT):
                if body is None:
                    r = await self.http.get(BASE + '/models')  # public; no Authorization header
                else:
                    r = await self.http.post(BASE + '/chat/completions', json=body, headers={
                        'Authorization': 'Bearer ' + self._key, 'x-opencode-session': session})
            meta.update(seconds=round(time.monotonic() - start, 3), status=r.status_code)
            if not r.is_success:
                text = r.text.lower()
                # Classify without logging raw error bodies, which can contain request metadata.
                if r.status_code in (402, 429) or re.search(r'quota|insufficient (?:balance|credit)|rate.?limit', text):
                    reason = 'quota/billing/rate limit'
                elif r.status_code == 413 or (r.status_code in (400, 422) and
                        re.search(r'too many tools|tools.{0,160}(?:maximum|max |limit|at most|too long|128)|'
                                  r'(?:maximum|at most|limit).{0,100}tools|context.length', text, re.S)):
                    reason = 'tool array or context limit'
                else:
                    reason = 'HTTP rejection (not classified as catalog limit)'
                meta['error'] = reason
                error = CatalogLimitError if reason == 'tool array or context limit' else BenchmarkError
                raise error(f'{label}: HTTP {r.status_code} {reason}')
            data = r.json()
            if body is None:
                if MODEL not in {m['id'] for m in data['data']}:
                    raise BenchmarkError('Requested model not listed')
                meta['listed'] = MODEL
                return None, meta
            model = data.get('model')
            meta.update(model=model, usage=numeric_tree(data.get('usage') or {}))
            meta.update(usage_counts(meta['usage']))
            if model != MODEL:
                raise BenchmarkError(f'{label}: unexpected response model (see requests.jsonl)')
            choice = data['choices'][0]
            meta['finish_reason'] = choice.get('finish_reason')
            return choice['message'], meta
        except BenchmarkError as exc:
            meta.setdefault('error', str(exc))
            raise
        except (httpx.HTTPError, TimeoutError, KeyError, TypeError, ValueError, IndexError) as exc:
            meta['error'] = type(exc).__name__
            raise BenchmarkError(f'{label}: {type(exc).__name__}; no retries') from None
        finally:
            if 'error' in meta:
                self.errors.append(dict(meta))
            self.save('requests.jsonl', meta, True)

    async def chat(self, label, session, messages, view):
        body = dict(model=MODEL, messages=messages, tools=view.get_definitions(), temperature=0,
                    thinking={'type': 'disabled'}, max_tokens=384, stream=False)
        return await self.request(label, session, body)


def view_for(registry, budget):
    config = ToolsConfig.model_validate({'schemaTokenBudget': budget})
    assert config.schema_token_budget == budget
    return tool_view(registry, config.schema_token_budget)


def ranked_reply(text, source):
    # Use only registered non-core names from the observed reply, *including unprefixed plugins*.
    return list(dict.fromkeys(s for s in re.findall(r'[\w-]+', text) if s not in CORE and source.has(s)))[:5]


def target_kind(source, name):
    return 'core' if name in CORE else 'plugin' if source.get(name).mcp_server is None else 'mcp'


def turn_cap(case, arm):
    if not case.steps:
        return 2
    deferred = sum(name not in CORE for name, _ in case.steps) if arm == 'search' else 0
    return len(case.steps) + deferred + 2  # execution + discovery + answer + one recovery turn


def total(counts):
    return sum(counts) if None not in counts else None


async def exercise(run, n, arm, case):
    # No promotions or edited fixture files carry over between cases/arms.
    source = catalog(n)
    view = view_for(source, 1 if arm == 'search' else 0)
    assert view.has(SEARCH) == (arm == 'search')
    start = time.monotonic()
    messages = [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': case.prompt}]
    label = f'{n}/{arm}/{case.id}'
    session = uuid.uuid4().hex
    calls, turns, attempts = [], [], []
    expected = [(name, step_args(name, ref)) for name, ref in case.steps]
    kinds = [target_kind(source, name) for name, _ in expected]
    core_case = 'core' in kinds
    first = None
    answer = None
    matched = 0
    had_error = False
    for turn in range(1, turn_cap(case, arm) + 1):
        offered = {s['function']['name'] for s in view.get_definitions()}
        message, meta = await run.chat(f'{label}/{turn}', session, messages, view)
        turns.append(meta)
        tools = message.get('tool_calls') or []
        if not tools:
            answer = message.get('content')
            break
        messages.append({k: message[k] for k in ('role', 'content', 'reasoning_content', 'tool_calls') if k in message})
        # Only execute what was offered on this request, never a real MCP service or arbitrary command.
        for call in tools:
            fn = call['function']
            name = fn['name']
            try:
                args = json.loads(fn['arguments'])
            except (ValueError, TypeError):
                args = None
            if name in offered and isinstance(args, dict):
                result = await view.execute(name, args)
                ok = not getattr(result, 'is_error', False)
            else:
                result, ok = 'Unavailable tool or malformed arguments.', False
            had_error |= not ok
            event = dict(turn=turn, name=name, args=args, ok=ok, output=str(result))
            calls.append(event)
            if name == SEARCH:
                event['hits'] = ranked_reply(str(result), source) if ok else []
                if first is None:
                    first = event['hits']
            else:
                step = (name, args)
                attempts.append(step)
                if ok and matched < len(expected) and step == expected[matched]:
                    matched += 1
            messages.append({'role': 'tool', 'tool_call_id': call['id'], 'content': str(result)})
    selected = (attempts == expected and not had_error and (not core_case or first is None)) if expected else not calls
    complete = (matched == len(expected) and case.answer in (answer or '')) if expected else (
        not calls and (answer or '').strip() == case.answer)
    if core_case and expected[0][0] == 'edit_file':
        complete = complete and source.get('edit_file').files[EDIT_PATH] == 'APPROVED'
    recall = None
    next_hit = None
    if arm == 'search' and expected and not core_case:
        recall = sum(name in (first or []) for name, _ in expected) / len(expected)
        next_hit = expected[0][0] in (first or [])
    tokens = [m['prompt'] for m in turns]
    row = dict(catalog=n, arm=arm, case=case.id, expected=expected, target_kinds=kinds,
               first_tool=calls[0]['name'] if calls else None, search_calls=sum(e['name'] == SEARCH for e in calls),
               core_direct=(attempts[:1] == expected[:1] and first is None) if core_case else None,
               first_search=first, first_recall_at_5=recall, first_step_hit_at_5=next_hit,
               clean_selection=selected, completed=complete, matched_steps=matched, rounds=len(turns),
               seconds=round(time.monotonic() - start, 3), prompt_tokens=tokens,
               totals={k: total([m[k] for m in turns]) for k in ('prompt', 'completion', 'cached', 'miss')},
               answer=answer, calls=calls)
    run.cases.append(row)
    run.save('cases.jsonl', row, True)
    print(f'{label}: complete={complete} clean={selected} first_recall={recall} rounds={len(tokens)} prompt={tokens}',
          flush=True)


def cache_messages(session):
    # Same synthetic context for both arms. The first measurement need not be a cold cache.
    prefix = f'Synthetic cache fixture {session}.\n' + '\n'.join(
        f'Synthetic depot {i:03d} accepts invoices on business days.' for i in range(120))
    return [{'role': 'system', 'content': prefix}, {'role': 'user', 'content': 'Reply only with READY.'}]


async def cache_probe(run, n, session, arm):
    messages = cache_messages(session)
    view = view_for(catalog(n), 0 if arm == 'eager' else 1)
    phases = ('warm', 'replay') if arm == 'eager' else ('warm', 'replay', 'first_after_promote', 'promoted_stable')
    prior = None
    for phase in phases:
        if phase == 'first_after_promote':
            before = list(view.get_definitions())
            await view.execute(SEARCH, {'query': 'warehouse available units'})
            after = view.get_definitions()
            assert view.has('warehouse_available_units') and len(after) > len(before) and after[:len(before)] == before
        label = f'cache/{n}/{arm}/{phase}'
        _, meta = await run.chat(label, session, messages, view)
        if phase in ('replay', 'promoted_stable'):
            assert prior == meta['payload_sha256']  # exact replay, not messages alone
        prior = meta['payload_sha256']
        run.cache.append({k: meta[k] for k in ('label', 'payload_sha256', 'messages_sha256', 'schemas_sha256',
                                                'tool_count', 'prompt', 'cached', 'miss', 'usage', 'seconds')})
        print(f"{label}: prompt={meta['prompt']} cached={meta['cached']} miss={meta['miss']}", flush=True)


def aggregate(run):
    groups = {}
    for n, arm in sorted({(r['catalog'], r['arm']) for r in run.cases}):
        rows = [r for r in run.cases if (r['catalog'], r['arm']) == (n, arm)]
        recall = [r for r in rows if r['first_recall_at_5'] is not None]
        plugin = [r for r in rows if 'plugin' in r['target_kinds']]
        core = [r for r in rows if r['core_direct'] is not None]
        groups[f'{n}/{arm}'] = dict(cases=len(rows), clean=sum(r['clean_selection'] for r in rows),
                                    completed=sum(r['completed'] for r in rows), recall_cases=len(recall),
                                    mean_first_recall=mean(r['first_recall_at_5'] for r in recall) if recall else None,
                                    first_step_hits=sum(r['first_step_hit_at_5'] for r in recall) if recall else None,
                                    plugin_target_cases=len(plugin), plugin_cases_completed=sum(r['completed'] for r in plugin),
                                    core_cases=len(core), core_direct=sum(r['core_direct'] for r in core),
                                    total_rounds=sum(r['rounds'] for r in rows),
                                    totals={k: total([r['totals'][k] for r in rows]) for k in ('prompt', 'completion', 'cached', 'miss')})
    lookup = {(r['catalog'], r['case'], r['arm']): r for r in run.cases}
    pairs = []
    for (n, case, arm), eager in lookup.items():
        search = lookup.get((n, case, 'search'))
        if arm == 'eager' and search:
            pairs.append(dict(catalog=n, case=case, extra_rounds=search['rounds'] - eager['rounds'],
                              both_completed=search['completed'] and eager['completed']))
    return groups, pairs


async def suite(run):
    await run.request('preflight/models', None)
    try:
        await exercise(run, 300, 'eager', CASES[0])
    except CatalogLimitError:
        if run.count != 2:
            raise  # only an initial full-schema rejection triggers a smaller comparison
        print('Full eager catalog rejected; matched comparisons will use 96 non-core + 7 core.', flush=True)
        full = False
    else:
        full = True
    cache_session = uuid.uuid4().hex
    for arm in ('search', 'eager'):
        await cache_probe(run, 300 if full else 96, cache_session, arm)
    for i, case in enumerate(CASES):
        arms = (('search', 'eager') if i % 2 else ('eager', 'search')) if full else ('search',)
        for arm in arms:
            if not i and arm == 'eager':
                continue
            await exercise(run, 300, arm, case)
    if not full:
        for i in (0, 1, 4):  # MCP, plugin and cross-source chained task; preserve both real cache arms

            for arm in (('search', 'eager') if i % 2 else ('eager', 'search')):
                await exercise(run, 96, arm, CASES[i])


def hashes():
    paths = ('scripts/benchmark_tool_search.py', 'nanobot/agent/tools/tool_search.py',
             'nanobot/agent/tools/tool_search_index.py', 'nanobot/agent/tools/registry.py', 'nanobot/agent/tools/base.py',
             'nanobot/config/schema.py', 'nanobot/agent/loop.py', 'nanobot/agent/subagent.py')
    files = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip()
    return dict(head=head, files=files, benchmark_checkout_sha256=digest(json.dumps([head, files], sort_keys=True)))


async def offline(n, plugin_only=False):
    reg = catalog(n, plugin_only=plugin_only)
    core = set() if plugin_only else set(CORE)
    schemas = reg.get_definitions()
    deferred = {s['function']['name']: s for s in schemas if s['function']['name'] not in core}
    assert len(deferred) == n
    tools = [reg.get(name) for name in deferred]
    plugin_count = sum(t.mcp_server is None for t in tools)
    assert plugin_count == (n if plugin_only else n // 2)
    estimated = reg.searchable_schema_tokens()
    compact = json.dumps(list(deferred.values()), ensure_ascii=False, separators=(',', ':')).encode()
    assert estimated == (len(compact) + 2) // 3
    assert view_for(reg, 0) is reg and view_for(reg, estimated) is reg
    view = view_for(reg, estimated - 1)
    initial = view.get_definitions()
    assert {s['function']['name'] for s in initial} == core | {SEARCH} == set(view.tool_names)
    if not plugin_only:
        assert all(reg.has(name) for c in CASES for name, _ in c.steps)
        assert await view.execute('exec', {'command': 'printf READY'}) == 'READY'
        for case in CASES[-2:]:
            name, ref = case.steps[0]
            assert await view.execute(name, step_args(name, ref)) == case.answer
        assert reg.get('edit_file').files[EDIT_PATH] == 'APPROVED'
    index = ToolSearchIndex(tools)
    for name, schema in deferred.items():
        assert index.search(name)[:1] == [name], name
        before = list(view.get_definitions())
        reply = await view.execute(SEARCH, {'query': name})
        assert ranked_reply(reply, reg)[:1] == [name], name
        after = view.get_definitions()
        assert after[:len(before)] == before and schema in after, name
        assert await view.execute(name, {'ref': 'DEMO-1'}) == value(name, 'DEMO-1'), name
    assert view_for(reg, 1).get_definitions() == initial
    if plugin_only:
        # Exercise natural keywords too, not just the exact-name rank override.
        query, target = 'distribution warehouse free quantity not reserved', 'warehouse_available_units'
        fresh = view_for(reg, 1)
        assert target in ranked_reply(await fresh.execute(SEARCH, {'query': query}), reg)
        assert await fresh.execute(target, {'ref': 'SKU-82'}) == value(target, 'SKU-82')
    return dict(non_core=n, plugin_only=plugin_only, mcp=n - plugin_count, plugin=plugin_count,
                initially_visible=[s['function']['name'] for s in initial], eager_schemas=len(schemas),
                schema_bytes=len(compact), searchable_schema_tokens=estimated, exact_rank1_and_executed=n,
                schemas_sha256=digest(json.dumps(schemas)))


def go_key():
    providers = json.loads((Path.home() / '.nanobot/config.json').read_text())['providers']
    for name in ('opencodeGo', 'opencode_go'):
        if key := (providers.get(name) or {}).get('apiKey'):
            return key
    raise BenchmarkError('No configured OpenCode Go apiKey')


async def main(live, max_requests):
    if not __debug__:
        raise BenchmarkError('Assertions required; do not use optimized Python.')
    for cls in (Tool, ToolRegistry, tool_view, ToolSearchIndex, ToolsConfig):
        if Path(sys.modules[cls.__module__].__file__).resolve() != ROOT / (cls.__module__.replace('.', '/') + '.py'):
            raise BenchmarkError('Wrong nanobot checkout; run from the checkout root with PYTHONPATH=.')
    initial = hashes()
    checks = [await offline(300), await offline(300, plugin_only=True), await offline(96)]
    print('Offline fixture checks passed: ' + json.dumps(checks), flush=True)
    if not live:
        print('No credentials or model calls. Checkout: ' + json.dumps(initial))
        return
    key = go_key()
    os.umask(0o077)
    if OUT.resolve() != OUT:
        raise BenchmarkError('Report path must not contain symlinks')
    OUT.mkdir(mode=0o700, parents=True, exist_ok=True)
    st = OUT.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise BenchmarkError('Unsafe report directory (must be private and owned by this user)')
    dest = OUT / uuid.uuid4().hex
    dest.mkdir(mode=0o700)
    print(f'Report: {dest}', flush=True)
    async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=TIMEOUT) as http:
        run = Run(http, key, dest, max_requests)
        run.save('plan.json', dict(model=MODEL, endpoint=BASE, hashes=initial, offline=checks, report_dir=str(dest),
                                   cases=[asdict(c) for c in CASES], limit=max_requests, timeout_seconds=TIMEOUT,
                                   config='tools.schemaTokenBudget', search_budget=1, eager_budget=0, limitations=LIMITATIONS))
        status = 'interrupted'
        try:
            await suite(run)
            status = 'complete'
        except BenchmarkError as exc:
            status = str(exc)
            raise
        finally:
            groups, pairs = aggregate(run)
            final = hashes()
            run.save('summary.json', dict(status=status, http_requests=run.count, errors=run.errors, groups=groups,
                                          pairs=pairs, cache=run.cache, limitations=LIMITATIONS, report_dir=str(dest),
                                          checkout_unchanged=final == initial, start=initial, end=final))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='send synthetic requests to OpenCode Go')
    parser.add_argument('--max-requests', type=int, default=LIMIT, help=f'total HTTP cap (1–{LIMIT})')
    args = parser.parse_args()
    if not 1 <= args.max_requests <= LIMIT:
        parser.error(f'--max-requests must be between 1 and {LIMIT}')
    try:
        asyncio.run(main(args.live, args.max_requests))
    except BenchmarkError as err:
        sys.exit(str(err))
