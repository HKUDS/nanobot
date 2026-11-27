"""Live OpenCode Go benchmark for the checkout's MCP discovery view (not the whole agent loop).

From the checkout with nanobot's test venv (or replace python with a sibling venv's python):
    PYTHONPATH=. python -B scripts/benchmark_mcp_tool_search.py             # offline fixture check
    PYTHONPATH=. python -B scripts/benchmark_mcp_tool_search.py --live      # consumes Go quota

Only synthetic schemas, messages and tool results go to the fixed official endpoint. No real
MCP connection, provider fallback, redirects, proxy env, SDK retries or nanobot agent config.
Only the Go apiKey is used from ~/.nanobot/config.json. Results are private local JSON/JSONL
under /tmp/nanobot-mcp-search-eval/, one directory per run. An interrupted run is not resumed.
At most 72 HTTP requests including the model list and cache probes; any quota error stops the run.
Use --max-requests N to set a stricter total cap. Both cache arms use identical messages and
session, without a flush; cache state, routing and model output are not deterministic.
Recall@5 is per MCP case, against all its required names, only on the first actual search call;
no search is a miss, and direct-answer cases are excluded. Clean selection requires the exact
ordered business calls/refs; completion allows recovery but checks both execution and final value.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import stat
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean

import httpx

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.mcp_tool_search import mcp_tool_view
from nanobot.agent.tools.registry import ToolRegistry

MODEL = "deepseek-v4.1-flash"
BASE = "https://opencode.ai/zen/go/v1"
LIMIT = 72
TIMEOUT = 50
ROOT = Path(__file__).resolve().parents[1]
OUT = Path("/tmp/nanobot-mcp-search-eval")
SYSTEM = ("Answer the user's request. For business records use read-only tools and report the exact "
          "value returned; do not guess. For general questions answer directly. Be concise.")

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


class Lookup(Tool):
    read_only = True
    _plugin_discoverable = False

    def __init__(self, server, scope, facet):
        self.mcp_server_name = server
        field, _, meaning = facet.partition(':')
        self._name = f'mcp_{server}_{field}'
        self._description = f'Read {meaning or field.replace("_", " ")} for {scope} by record identifier.'

    @property
    def mcp_server(self):
        return self.mcp_server_name

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


def catalog(n):
    registry = ToolRegistry()
    for services, specific in DOMAINS:
        for server, scope in services:
            for facet in (*specific, *COMMON)[:n // 12]:
                registry.register(Lookup(server, scope, facet))
    assert len(registry.tool_names) == n
    return registry


@dataclass(frozen=True)
class Case:
    id: str
    prompt: str
    steps: tuple = ()  # ordered (registered name, exact ref); second ref comes only from first result

    @property
    def answer(self):
        return value(*self.steps[-1]) if self.steps else '42'


LINK = 'mcp_payables_shipment_link'
CASES = (
    Case('en_balance', 'What is the unpaid balance on supplier invoice V-410?',
         (('mcp_payables_unpaid_balance', 'V-410'),)),
    Case('zh_units', '配送仓库的 SKU-82 现在还有多少件可以分配给新订单？不要给我包含已锁定库存的总数。',
         (('mcp_warehouse_available_units', 'SKU-82'),)),
    Case('en_paraphrase', 'An employee says their trip expenses finally landed in their bank account. '
         'For claim E-73, when did the money go out?', (('mcp_employeeclaims_payout_date', 'E-73'),)),
    Case('zh_handover', '想确认客户签收了我们发出的那批货，麻烦查一下运单 O-38 的交接回执编号。',
         (('mcp_outbound_proof_of_delivery', 'O-38'),)),
    Case('en_chain', 'Start with vendor bill B-990. Find its linked incoming shipment, then give me the '
         'handover receipt code for that shipment.', ((LINK, 'B-990'),
                                                      ('mcp_inbound_proof_of_delivery', value(LINK, 'B-990')))),
    Case('zh_plain', '把六乘七的结果用阿拉伯数字写出来，只给数字。'),
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
    return {'prompt': u.get('prompt_tokens'), 'cached': cached, 'miss': u.get('prompt_cache_miss_tokens')}


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
            meta.update(tool_count=len(body['tools']), payload_sha256=digest(json.dumps(body)))
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
                self.errors.append(dict(meta))
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
        except (httpx.HTTPError, TimeoutError, KeyError, ValueError, IndexError) as exc:
            meta['error'] = type(exc).__name__
            raise BenchmarkError(f'{label}: {type(exc).__name__}; no retries') from None
        finally:
            self.save('requests.jsonl', meta, True)

    async def chat(self, label, session, messages, view):
        body = dict(model=MODEL, messages=messages, tools=view.get_definitions(), temperature=0,
                    thinking={'type': 'disabled'}, max_tokens=384, stream=False)
        return await self.request(label, session, body)


async def exercise(run, source, n, arm, case):
    # The positive budget deliberately forces the same discovery path even on the paired subset.
    view = mcp_tool_view(source, 1 if arm == 'search' else 0)
    assert view.has('tool_search') == (arm == 'search')
    messages = [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': case.prompt}]
    label = f'{n}/{arm}/{case.id}'
    session = uuid.uuid4().hex
    calls, tokens, attempts = [], [], []
    first = None
    answer = None
    matched = 0
    had_error = False
    for turn in range(1, (7 if len(case.steps) == 2 else 5) + 1):
        message, meta = await run.chat(f'{label}/{turn}', session, messages, view)
        tokens.append(meta['prompt'])
        tools = message.get('tool_calls') or []
        if not tools:
            answer = message.get('content')
            break
        messages.append({k: message[k] for k in ('role', 'content', 'reasoning_content', 'tool_calls') if k in message})
        # Only execute what was offered on this request, never a real MCP service or arbitrary command.
        offered = set(view.tool_names)
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
            if name == 'tool_search':
                if first is None:
                    # Score what the model actually saw, without re-querying the index.
                    first = [s for s in re.findall(r'\bmcp_\w+', str(result)) if source.has(s)][:5] if ok else []
            else:
                step = (name, args.get('ref') if isinstance(args, dict) else None)
                attempts.append(step)
                if ok and matched < len(case.steps) and step == case.steps[matched]:
                    matched += 1
            messages.append({'role': 'tool', 'tool_call_id': call['id'], 'content': str(result)})
    selected = (attempts == list(case.steps) and not had_error) if case.steps else not calls
    complete = (matched == len(case.steps) and case.answer in (answer or '')) if case.steps else (
        not calls and (answer or '').strip() == case.answer)
    recall = None
    next_hit = None
    if arm == 'search' and case.steps:
        recall = sum(name in (first or []) for name, _ in case.steps) / len(case.steps)
        next_hit = case.steps[0][0] in (first or [])
    row = dict(catalog=n, arm=arm, case=case.id, first_search=first, first_recall_at_5=recall,
               first_step_hit_at_5=next_hit, clean_selection=selected, completed=complete, matched_steps=matched,
               rounds=len(tokens), prompt_tokens=tokens, answer=answer, calls=calls)
    run.cases.append(row)
    run.save('cases.jsonl', row, True)
    print(f'{label}: complete={complete} clean={selected} first_recall={recall} rounds={len(tokens)} prompt={tokens}',
          flush=True)


def cache_messages(session):
    # Same synthetic context for both arms. The first measurement need not be a cold cache.
    prefix = f'Synthetic cache fixture {session}.\n' + '\n'.join(
        f'Synthetic depot {i:03d} accepts invoices on business days.' for i in range(120))
    return [{'role': 'system', 'content': prefix}, {'role': 'user', 'content': 'Reply only with READY.'}]


async def cache_probe(run, source, session, *, eager=False):
    messages = cache_messages(session)
    view = mcp_tool_view(source, 0 if eager else 1)
    phases = ('eager_warm', 'eager_replay') if eager else (
        'warm', 'replay', 'first_after_promote', 'promoted_stable')
    for phase in phases:
        if phase == 'first_after_promote':
            before = list(view.get_definitions())
            await view.execute('tool_search', {'query': 'payables unpaid balance'})
            after = view.get_definitions()
            assert len(after) > len(before) and after[:len(before)] == before
        _, meta = await run.chat('cache/' + phase, session, messages, view)
        run.cache.append({k: meta[k] for k in ('label', 'payload_sha256', 'tool_count', 'prompt', 'cached', 'miss')})
        print(f"cache/{phase}: prompt={meta['prompt']} cached={meta['cached']} miss={meta['miss']}", flush=True)


def aggregate(run):
    groups = {}
    for n, arm in sorted({(r['catalog'], r['arm']) for r in run.cases}):
        rows = [r for r in run.cases if (r['catalog'], r['arm']) == (n, arm)]
        recall = [r for r in rows if r['first_recall_at_5'] is not None]
        usage = [t for r in rows for t in r['prompt_tokens']]
        groups[f'{n}/{arm}'] = dict(cases=len(rows), clean=sum(r['clean_selection'] for r in rows),
                                    completed=sum(r['completed'] for r in rows), recall_cases=len(recall),
                                    mean_first_recall=mean(r['first_recall_at_5'] for r in recall) if recall else None,
                                    first_step_hits=sum(r['first_step_hit_at_5'] for r in recall) if recall else None,
                                    prompt_tokens=sum(usage) if None not in usage else None)
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
    source = catalog(300)
    try:
        await exercise(run, source, 300, 'eager', CASES[0])
    except CatalogLimitError:
        if run.count != 2:
            raise  # only an initial full-schema rejection triggers a smaller comparison
        print('Eager 300 rejected by provider; testing a matched 96-schema subset.', flush=True)
        full = False
    else:
        full = True
    cache_session = uuid.uuid4().hex
    await cache_probe(run, source, cache_session)
    if full:
        await cache_probe(run, source, cache_session, eager=True)
    for i, case in enumerate(CASES):
        arms = (('search', 'eager') if i % 2 else ('eager', 'search')) if full else ('search',)
        for arm in arms:
            if not i and arm == 'eager':
                continue
            await exercise(run, source, 300, arm, case)
    if not full:
        subset = catalog(96)
        for i in (0, 1, 4, 5):
            for arm in (('search', 'eager') if i % 2 else ('eager', 'search')):
                await exercise(run, subset, 96, arm, CASES[i])


def hashes():
    return {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in (
        'scripts/benchmark_mcp_tool_search.py', 'nanobot/agent/tools/mcp_tool_search.py',
        'nanobot/agent/tools/mcp_search_index.py', 'nanobot/agent/tools/registry.py', 'nanobot/agent/tools/base.py')}


def go_key():
    providers = json.loads((Path.home() / '.nanobot/config.json').read_text())['providers']
    for name in ('opencodeGo', 'opencode_go'):
        if key := (providers.get(name) or {}).get('apiKey'):
            return key
    raise BenchmarkError('No configured OpenCode Go apiKey')


async def main(live, max_requests):
    if Path(sys.modules[mcp_tool_view.__module__].__file__).resolve() != ROOT / 'nanobot/agent/tools/mcp_tool_search.py':
        raise BenchmarkError('Wrong nanobot checkout; run from the checkout root with PYTHONPATH=.')
    for n in (300, 96):
        reg = catalog(n)
        assert all(reg.has(name) for c in CASES for name, _ in c.steps)
        view = mcp_tool_view(reg, 1)
        assert view.tool_names == ['tool_search'] and len(mcp_tool_view(reg, 0).tool_names) == n
        await view.execute('tool_search', {'query': LINK})
        assert await view.execute(LINK, {'ref': 'B-990'}) == value(LINK, 'B-990')
    if not live:
        print('Offline catalog, view, promotion and linked-reference checks passed; no model calls.')
        return
    key = go_key()
    os.umask(0o077)
    OUT.mkdir(mode=0o700, exist_ok=True)
    st = OUT.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise BenchmarkError('Unsafe report directory (must be private and owned by this user)')
    dest = OUT / uuid.uuid4().hex
    dest.mkdir(mode=0o700)
    print(f'Report: {dest}', flush=True)
    async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=TIMEOUT) as http:
        run = Run(http, key, dest, max_requests)
        initial = hashes()
        run.save('plan.json', dict(model=MODEL, endpoint=BASE, hashes=initial, cases=[asdict(c) for c in CASES],
                                   limit=max_requests, timeout_seconds=TIMEOUT, search_budget=1, eager_budget=0))
        status = 'interrupted'
        try:
            await suite(run)
            status = 'complete'
        except BenchmarkError as exc:
            status = str(exc)
            raise
        finally:
            groups, pairs = aggregate(run)
            run.save('summary.json', dict(status=status, http_requests=run.count, errors=run.errors, groups=groups,
                                          pairs=pairs, cache=run.cache, checkout_unchanged=hashes() == initial))


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
