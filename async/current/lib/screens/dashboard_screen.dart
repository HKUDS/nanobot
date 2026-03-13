import 'dart:convert';
import 'package:flutter/material.dart' hide Text, Container;
import 'package:provider/provider.dart';
import 'package:http/http.dart' as http;
import '../widgets/terminal_widgets.dart';
import '../services/c2_service.dart';
import 'jobs_screen.dart';

class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key});
  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  Map<String, dynamic> _revenue = {};
  List<dynamic> _jobs = [];
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final svc = context.read<C2Service>();
    if (!svc.connected) {
      setState(() => _loading = false);
      return;
    }
    try {
      final r = await http.get(
        Uri.parse('${svc.activeBaseUrl}/memory/revenue'),
        headers: {'Authorization': 'Bearer ${svc.token}'},
      ).timeout(const Duration(seconds: 8));
      final j = await http.get(
        Uri.parse('${svc.activeBaseUrl}/memory/jobs?limit=30'),
        headers: {'Authorization': 'Bearer ${svc.token}'},
      ).timeout(const Duration(seconds: 8));
      if (mounted) {
        setState(() {
          _revenue = r.statusCode == 200 ? jsonDecode(r.body) : {};
          _jobs = j.statusCode == 200
              ? (jsonDecode(j.body)['jobs'] as List? ?? [])
              : [];
          _loading = false;
        });
      }
    } catch (_) {
      setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final rev = _revenue;
    final thisMonth = (rev['this_month'] as num?)?.toDouble() ?? 0;
    final gap = (rev['gap'] as num?)?.toDouble() ?? 10000;
    final completed = rev['completed_jobs'] as int? ?? 0;
    final active = rev['active_jobs'] as int? ?? 0;

    return _loading
        ? const Center(
            child: CircularProgressIndicator(color: LC.green, strokeWidth: 2))
        : RefreshIndicator(
            onRefresh: _load,
            color: LC.green,
            child: ListView(padding: const EdgeInsets.all(14), children: [
              // Big revenue hero
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: LC.card,
                  border: Border.all(color: LC.border),
                  borderRadius: BorderRadius.circular(3),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('THIS MONTH', style: LC.mono(size: 8, spacing: 3)),
                    const SizedBox(height: 6),
                    Text('\$${thisMonth.toStringAsFixed(2)}',
                        style: LC.head(
                            size: 38,
                            w: FontWeight.w700,
                            color: LC.green,
                            spacing: 1)),
                    const SizedBox(height: 4),
                    Text('\$${gap.toStringAsFixed(2)} TO MAY 9TH TARGET',
                        style: LC.mono(size: 9, spacing: 1)),
                    const SizedBox(height: 10),
                    ClipRRect(
                      borderRadius: BorderRadius.circular(2),
                      child: LinearProgressIndicator(
                        value: (thisMonth / 10000).clamp(0.0, 1.0),
                        minHeight: 3,
                        backgroundColor: LC.bg2,
                        valueColor:
                            const AlwaysStoppedAnimation<Color>(LC.green),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 8),

              // Stat row
              Row(children: [
                Expanded(
                    child: StatCard(
                        label: 'COMPLETED',
                        value: '$completed',
                        valueColor: LC.green)),
                const SizedBox(width: 6),
                Expanded(
                    child: StatCard(
                        label: 'ACTIVE',
                        value: '$active',
                        valueColor: LC.amber,
                        accentColor: LC.amber)),
                const SizedBox(width: 6),
                Expanded(
                    child: StatCard(
                        label: 'ALL TIME',
                        value:
                            '\$${((rev['total_revenue'] as num?)?.toDouble() ?? 0).toStringAsFixed(0)}')),
              ]),
              const SizedBox(height: 12),

              // Jobs list
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  SectionLabel('JOBS — ${_jobs.length}'),
                  GestureDetector(
                    onTap: () => Navigator.push(
                        context,
                        MaterialPageRoute(
                            builder: (_) => Scaffold(
                                  backgroundColor: LC.bg,
                                  appBar: AppBar(
                                    backgroundColor: LC.bg2,
                                    title: Text('JOBS',
                                        style: LC.head(
                                            size: 16,
                                            w: FontWeight.w700,
                                            color: LC.green,
                                            spacing: 3)),
                                    iconTheme:
                                        const IconThemeData(color: LC.green),
                                  ),
                                  body: const JobsScreen(),
                                ))),
                    child: Padding(
                      padding: const EdgeInsets.only(right: 4, top: 2),
                      child: Text('VIEW ALL  >',
                          style: LC.mono(size: 8, color: LC.cyan, spacing: 2)),
                    ),
                  ),
                ],
              ),
              ..._jobs.map((j) {
                final status = j['status'] as String? ?? '';
                final color = status == 'delivered'
                    ? LC.green
                    : status == 'running'
                        ? LC.cyan
                        : LC.amber;
                return Container(
                  margin: const EdgeInsets.only(bottom: 4),
                  padding:
                      const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                  decoration: BoxDecoration(
                    color: LC.card,
                    border: Border.all(color: LC.border),
                    borderRadius: BorderRadius.circular(3),
                  ),
                  child: Row(children: [
                    Container(
                        width: 3,
                        height: 36,
                        color: color,
                        margin: const EdgeInsets.only(right: 10)),
                    Expanded(
                        child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(j['title'] as String? ?? '',
                            style: LC.head(
                                size: 12,
                                w: FontWeight.w600,
                                color: LC.text,
                                spacing: 0.3),
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis),
                        const SizedBox(height: 2),
                        Text('${j['platform'] ?? ''} · ${status.toUpperCase()}',
                            style: LC.mono(size: 8, spacing: 1.5)),
                      ],
                    )),
                    Text(
                        '\$${(j['revenue'] as num?)?.toStringAsFixed(0) ?? '0'}',
                        style: LC.head(
                            size: 14,
                            w: FontWeight.w700,
                            color: LC.green,
                            spacing: 0)),
                  ]),
                );
              }),

              if (_jobs.isEmpty)
                Center(
                    child: Padding(
                  padding: const EdgeInsets.only(top: 40),
                  child:
                      Text('NO JOBS YET', style: LC.mono(size: 11, spacing: 3)),
                )),

              const SizedBox(height: 20),
            ]),
          );
  }
}
