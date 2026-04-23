import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart' hide Text, Container;
import 'package:provider/provider.dart';
import 'package:http/http.dart' as http;
import '../../widgets/terminal_widgets.dart';
import '../../services/c2_service.dart';

class ChatView extends StatefulWidget {
  const ChatView({super.key});
  @override
  State<ChatView> createState() => _ChatViewState();
}

class _ChatViewState extends State<ChatView> {
  final _inputCtrl = TextEditingController();
  final _scrollCtrl = ScrollController();
  final List<_Msg> _messages = [];
  bool _typing = false;
  String _activeQuick = 'UPWORK';

  static const _quickItems = [
    ('UPWORK', 'Search Upwork for research jobs posted today'),
    ('CRYPTO', 'Give me a crypto market summary with prices'),
    ('BRIEFING', 'Give me a morning briefing'),
    ('JOBS', 'What jobs are currently active'),
    ('REVENUE', 'What is my revenue total this month'),
    ('ALERTS', 'What alerts do I have right now'),
  ];

  @override
  void initState() {
    super.initState();
    _messages.add(_Msg(
      text: 'Good morning, Boss. Lumina is online. What do you need?',
      fromLumina: true,
    ));
  }

  @override
  void dispose() {
    _inputCtrl.dispose();
    _scrollCtrl.dispose();
    super.dispose();
  }

  void _addMsg(_Msg msg) {
    if (!mounted) return;
    setState(() => _messages.add(msg));
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollCtrl.hasClients) {
        _scrollCtrl.animateTo(
          _scrollCtrl.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  Future<void> _send(String text) async {
    if (text.trim().isEmpty) return;
    _inputCtrl.clear();
    _addMsg(_Msg(text: text, fromLumina: false));
    setState(() => _typing = true);

    final svc = context.read<C2Service>();
    if (!svc.connected) {
      setState(() => _typing = false);
      _addMsg(_Msg(
        text: 'Cloud connection is offline. Check connection in Settings.',
        fromLumina: true,
      ));
      return;
    }

    try {
      final r = await http
          .post(
            Uri.parse('${svc.activeBaseUrl}/agent/command'),
            headers: {
              'Authorization': 'Bearer ${svc.token}',
              'Content-Type': 'application/json',
            },
            body: jsonEncode({'command': text}),
          )
          .timeout(const Duration(seconds: 90));

      if (mounted) {
        setState(() => _typing = false);
        if (r.statusCode == 200) {
          final data = jsonDecode(r.body);
          final result = data['result'] as String? ?? '';
          _addMsg(
              _Msg(text: result.isEmpty ? 'Done.' : result, fromLumina: true));
        } else {
          _addMsg(_Msg(
              text: 'Error ${r.statusCode} — try again.', fromLumina: true));
        }
      }
    } catch (e) {
      if (mounted) {
        setState(() => _typing = false);
        _addMsg(_Msg(
            text:
                'Connection error — the active cloud node may be unreachable.',
            fromLumina: true));
      }
    }
  }

  void _quickTap(String label, String cmd) {
    setState(() => _activeQuick = label);
    _inputCtrl.text = cmd;
    _inputCtrl.selection =
        TextSelection.fromPosition(TextPosition(offset: cmd.length));
  }

  @override
  Widget build(BuildContext context) {
    return Column(children: [
      // Quick Actions Scroll
      Container(
        color: LC.bg2,
        padding: const EdgeInsets.only(left: 14, right: 14, bottom: 10),
        child: SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: Row(
            children: _quickItems
                .map((item) => Padding(
                      padding: const EdgeInsets.only(right: 5),
                      child: QuickAction(
                        label: item.$1,
                        active: _activeQuick == item.$1,
                        onTap: () => _quickTap(item.$1, item.$2),
                      ),
                    ))
                .toList(),
          ),
        ),
      ),

      const SizedBox(height: 6),

      // Chat Container
      Expanded(
        child: Container(
          margin: const EdgeInsets.symmetric(horizontal: 14),
          decoration: BoxDecoration(
            color: LC.card,
            border: Border.all(color: LC.border),
            borderRadius: BorderRadius.circular(3),
          ),
          child: Column(children: [
            // Status/Header
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
              decoration: BoxDecoration(
                  border: Border(bottom: BorderSide(color: LC.border))),
              child: Row(children: [
                Text('LUMINA CC // ONLINE',
                    style: LC.head(
                        size: 10,
                        w: FontWeight.w600,
                        color: LC.dim,
                        spacing: 2)),
                const Spacer(),
                Text(_typing ? 'WORKING...' : 'READY',
                    style: LC.mono(
                        size: 8,
                        spacing: 2,
                        color: _typing ? LC.amber : LC.green)),
              ]),
            ),
            // Messages List
            Expanded(
              child: ListView.separated(
                controller: _scrollCtrl,
                padding: const EdgeInsets.all(12),
                itemCount: _messages.length,
                separatorBuilder: (_, __) => const SizedBox(height: 12),
                itemBuilder: (_, i) => ChatBubble(
                  text: _messages[i].text,
                  fromLumina: _messages[i].fromLumina,
                ),
              ),
            ),
            if (_typing)
              const Padding(
                  padding: EdgeInsets.all(10), child: TypingIndicator()),

            // Input Area
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                  border: Border(top: BorderSide(color: LC.border))),
              child: Row(children: [
                Expanded(
                  child: TextField(
                    controller: _inputCtrl,
                    style: LC.head(size: 14, color: LC.text, spacing: 0),
                    decoration: const InputDecoration(
                      hintText: 'Ask Lumina anything...',
                      border: InputBorder.none,
                      isDense: true,
                    ),
                    onSubmitted: _send,
                  ),
                ),
                GestureDetector(
                  onTap: () => _send(_inputCtrl.text),
                  child: const Icon(Icons.send, color: LC.green, size: 20),
                ),
              ]),
            ),
          ]),
        ),
      ),
      const SizedBox(height: 14),
    ]);
  }
}

class _Msg {
  final String text;
  final bool fromLumina;
  _Msg({required this.text, required this.fromLumina});
}
