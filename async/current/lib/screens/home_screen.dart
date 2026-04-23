import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart' hide Text, Container;
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import 'package:http/http.dart' as http;
import '../widgets/terminal_widgets.dart';
import '../services/c2_service.dart';
import 'alerts_screen.dart';
import 'memory_screen.dart';
import 'local_agent_screen.dart';
import 'agent_screen.dart';
import 'models_screen.dart';
import 'mcp_screen.dart';
import 'cloud_screen.dart';
import 'dashboard_screen.dart';
import 'jobs_screen.dart';
import 'chat/chat_view.dart';

// ── LUMINA COMMAND CENTER ─────────────────────────
// Main screen. Everything in 2 taps.
// Chat + Voice side by side.
// Status = one dot.
// Quick actions across the top.
// Stat cards for jobs, clients, alerts.
// Revenue bar always visible.

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});
  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  int _navIdx = 0;

  // Navigation screens
  final _screens = [
    const _MainCommand(),
    const DashboardScreen(),
    const LocalAgentScreen(),
    const AlertsScreen(),
    const _MoreScreen(),
  ];

  @override
  Widget build(BuildContext context) {
    return AnnotatedRegion<SystemUiOverlayStyle>(
      value: SystemUiOverlayStyle.light.copyWith(
        statusBarColor: LC.bg,
        statusBarIconBrightness: Brightness.light,
      ),
      child: Scaffold(
        backgroundColor: LC.bg,
        body: IndexedStack(
          index: _navIdx,
          children: _screens,
        ),
        bottomNavigationBar: LuminaNavBar(
          current: _navIdx,
          onTap: (i) => setState(() => _navIdx = i),
        ),
      ),
    );
  }
}

// ── MAIN COMMAND VIEW ─────────────────────────────
class _MainCommand extends StatefulWidget {
  const _MainCommand();
  @override
  State<_MainCommand> createState() => _MainCommandState();
}

class _MainCommandState extends State<_MainCommand> {
  int _alerts = 0;
  TermStatus _sysStatus = TermStatus.online;
  late Timer _refreshTimer;

  @override
  void initState() {
    super.initState();
    _loadStats();
    _refreshTimer =
        Timer.periodic(const Duration(seconds: 30), (_) => _loadStats());
  }

  @override
  void dispose() {
    _refreshTimer.cancel();
    super.dispose();
  }

  Future<void> _loadStats() async {
    final svc = context.read<C2Service>();
    if (!svc.connected) {
      if (mounted) setState(() => _sysStatus = TermStatus.offline);
      return;
    }
    try {
      final r = await http.get(
        Uri.parse('${svc.activeBaseUrl}/status'),
        headers: {'Authorization': 'Bearer ${svc.token}'},
      ).timeout(const Duration(seconds: 8));
      if (r.statusCode == 200 && mounted) {
        final data = jsonDecode(r.body);
        setState(() {
          _sysStatus = TermStatus.online;
          final alerts = data['alerts'] as Map<String, dynamic>? ?? {};
          _alerts = (alerts['unread'] as int?) ?? 0;
        });
      }
    } catch (_) {
      if (mounted) setState(() => _sysStatus = TermStatus.degraded);
    }
  }

  @override
  Widget build(BuildContext context) {
    final top = MediaQuery.of(context).padding.top;
    return Column(children: [
      // ── TOP BAR ─────────────────────────────────
      Container(
        color: LC.bg2,
        padding:
            EdgeInsets.only(top: top + 10, left: 18, right: 18, bottom: 10),
        child: Row(children: [
          Text('LUMINA',
              style: LC.head(
                  size: 26, w: FontWeight.w700, color: LC.green, spacing: 6)),
          const Spacer(),
          StatusDot(status: _sysStatus, size: 14),
          const SizedBox(width: 12),
          AlertBadge(_alerts),
        ]),
      ),
      // ── CHAT VIEW ───────────────────────────────
      const Expanded(child: ChatView()),
    ]);
  }
}

// ── MORE SCREEN ───────────────────────────────────
class _MoreScreen extends StatelessWidget {
  const _MoreScreen();

  @override
  Widget build(BuildContext context) {
    final top = MediaQuery.of(context).padding.top;
    return Column(children: [
      Container(
        color: LC.bg2,
        padding:
            EdgeInsets.only(top: top + 10, left: 18, right: 18, bottom: 10),
        child: Row(children: [
          Text('MORE',
              style: LC.head(
                  size: 22, w: FontWeight.w700, color: LC.text, spacing: 4)),
        ]),
      ),
      Expanded(
        child: ListView(
          padding: const EdgeInsets.all(14),
          children: [
            _moreItem(context, 'JOBS', Icons.work_outline, const JobsScreen()),
            _moreItem(
                context, 'MEMORY', Icons.memory_outlined, const MemoryScreen()),
            _moreItem(context, 'AGENT', Icons.smart_toy_outlined, const AgentScreen()),
            _moreItem(context, 'MODELS', Icons.psychology_outlined, const ModelsScreen()),
            _moreItem(context, 'MCP SERVERS', Icons.extension_outlined, const McpScreen()),
            _moreItem(context, 'CLOUD', Icons.cloud_outlined, const CloudScreen()),
            _moreItem(context, 'SETTINGS', Icons.settings_outlined, const CloudSettingsScreen()),
          ],
        ),
      ),
    ]);
  }

  Widget _moreItem(
      BuildContext ctx, String label, IconData icon, Widget screen) {
    return GestureDetector(
      onTap: () => Navigator.push(
          ctx,
          MaterialPageRoute(
              builder: (_) => Scaffold(
                    backgroundColor: LC.bg,
                    appBar: AppBar(
                      backgroundColor: LC.bg2,
                      title: Text(label,
                          style: LC.head(
                              size: 16,
                              w: FontWeight.w700,
                              color: LC.green,
                              spacing: 3)),
                      iconTheme: const IconThemeData(color: LC.green),
                    ),
                    body: screen,
                  ))),
      child: Container(
        margin: const EdgeInsets.only(bottom: 6),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
        decoration: BoxDecoration(
          color: LC.card,
          border: Border.all(color: LC.border),
          borderRadius: BorderRadius.circular(3),
        ),
        child: Row(children: [
          Icon(icon, color: LC.dim, size: 18),
          const SizedBox(width: 12),
          Text(label, style: LC.head(size: 13, color: LC.text, spacing: 1)),
          const Spacer(),
          const Icon(Icons.chevron_right, color: LC.border, size: 16),
        ]),
      ),
    );
  }
}
