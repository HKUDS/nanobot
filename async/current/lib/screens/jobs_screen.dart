import 'dart:convert';
import 'package:flutter/material.dart' hide Text, Container;
import 'package:provider/provider.dart';
import 'package:http/http.dart' as http;
import '../widgets/terminal_widgets.dart';
import '../services/c2_service.dart';

// ── JOB ENTRY MODEL ────────────────────────────────

class JobEntry {
  final String id;
  final String title;
  final String platform;
  final String? clientName;
  final String? clientId;
  final String status;
  final double revenue;
  final String? resultSummary;
  final String? modelUsed;
  final String createdAt;
  final String? deliveredAt;

  JobEntry({
    required this.id,
    required this.title,
    required this.platform,
    this.clientName,
    this.clientId,
    required this.status,
    required this.revenue,
    this.resultSummary,
    this.modelUsed,
    required this.createdAt,
    this.deliveredAt,
  });

  factory JobEntry.fromJson(Map<String, dynamic> j) => JobEntry(
        id: j['id'] ?? '',
        title: j['title'] ?? 'Untitled Job',
        platform: j['platform'] ?? 'unknown',
        clientName: j['client_name'],
        clientId: j['client_id'],
        status: j['status'] ?? 'pending',
        revenue: (j['revenue'] as num?)?.toDouble() ?? 0.0,
        resultSummary: j['result_summary'],
        modelUsed: j['model_used'],
        createdAt: j['created_at'] ?? '',
        deliveredAt: j['delivered_at'],
      );

  Color get statusColor => switch (status.toLowerCase()) {
        'delivered' => LC.green,
        'running' => LC.cyan,
        'failed' => LC.danger,
        'pending' => LC.amber,
        _ => LC.textDim,
      };
}

// ── JOBS SCREEN ───────────────────────────────────

class JobsScreen extends StatefulWidget {
  const JobsScreen({super.key});
  @override
  State<JobsScreen> createState() => _JobsScreenState();
}

class _JobsScreenState extends State<JobsScreen> {
  List<JobEntry> _jobs = [];
  bool _loading = true;
  String _filter = 'ALL';

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
        Uri.parse('${svc.activeBaseUrl}/memory/jobs?limit=50'),
        headers: {'Authorization': 'Bearer ${svc.token}'},
      ).timeout(const Duration(seconds: 8));

      if (mounted && r.statusCode == 200) {
        final data = jsonDecode(r.body);
        final List list = data['jobs'] ?? [];
        setState(() {
          _jobs = list.map((j) => JobEntry.fromJson(j)).toList();
          _loading = false;
        });
      }
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _updateStatus(String id, String status) async {
    final svc = context.read<C2Service>();
    try {
      final r = await http.patch(
        Uri.parse('${svc.activeBaseUrl}/memory/jobs/$id'),
        headers: {
          'Authorization': 'Bearer ${svc.token}',
          'Content-Type': 'application/json',
        },
        body: jsonEncode({'status': status}),
      );
      if (r.statusCode == 200) {
        _load();
      }
    } catch (_) {}
  }

  List<JobEntry> get _filteredJobs {
    if (_filter == 'ALL') return _jobs;
    return _jobs
        .where((j) => j.status.toUpperCase() == _filter.toUpperCase())
        .toList();
  }

  @override
  Widget build(BuildContext context) {
    return Column(children: [
      // Sub-header / Filters
      Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        color: LC.bg2,
        child: Row(children: [
          _filterBtn('ALL'),
          const SizedBox(width: 12),
          _filterBtn('RUNNING'),
          const SizedBox(width: 12),
          _filterBtn('PENDING'),
          const SizedBox(width: 12),
          _filterBtn('DELIVERED'),
          const Spacer(),
          GestureDetector(
            onTap: _load,
            child: const Icon(Icons.refresh, color: LC.dim, size: 16),
          ),
        ]),
      ),

      Expanded(
        child: _loading
            ? const Center(
                child:
                    CircularProgressIndicator(color: LC.green, strokeWidth: 2))
            : _filteredJobs.isEmpty
                ? Center(
                    child: Text(
                        'NO ${_filter == 'ALL' ? '' : '$_filter '}JOBS FOUND',
                        style: LC.mono(size: 11, spacing: 3)))
                : ListView.separated(
                    padding: const EdgeInsets.all(14),
                    itemCount: _filteredJobs.length,
                    separatorBuilder: (_, __) => const SizedBox(height: 6),
                    itemBuilder: (_, i) {
                      final j = _filteredJobs[i];
                      return _JobCard(
                        job: j,
                        onDeliver: () => _updateStatus(j.id, 'delivered'),
                      );
                    },
                  ),
      ),
    ]);
  }

  Widget _filterBtn(String label) {
    final active = _filter == label;
    return GestureDetector(
      onTap: () => setState(() => _filter = label),
      child: Text(
        label,
        style: LC.mono(
          size: 8,
          color: active ? LC.green : LC.dim,
          spacing: 1.5,
          weight: active ? FontWeight.bold : FontWeight.normal,
        ),
      ),
    );
  }
}

class _JobCard extends StatelessWidget {
  final JobEntry job;
  final VoidCallback onDeliver;

  const _JobCard({required this.job, required this.onDeliver});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: LC.card,
        border: Border.all(color: LC.border),
        borderRadius: BorderRadius.circular(2),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
              color: job.statusColor.withValues(alpha: 0.15),
              child: Text(job.status.toUpperCase(),
                  style: LC.mono(size: 7, color: job.statusColor, spacing: 2)),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: Text(job.title,
                  style: LC.head(
                      size: 13,
                      w: FontWeight.w600,
                      color: LC.text,
                      spacing: 0.3)),
            ),
            Text('\$${job.revenue.toStringAsFixed(0)}',
                style: LC.head(
                    size: 14, w: FontWeight.w700, color: LC.green, spacing: 0)),
          ]),
          const SizedBox(height: 6),
          Row(children: [
            Text(job.platform.toUpperCase(),
                style: LC.mono(size: 8, color: LC.amber, spacing: 1)),
            Text('  //  ', style: LC.mono(size: 8, color: LC.border)),
            Text(job.createdAt.substring(0, 10),
                style: LC.mono(size: 8, color: LC.dim)),
            if (job.clientName != null) ...[
              Text('  //  ', style: LC.mono(size: 8, color: LC.border)),
              Text(job.clientName!.toUpperCase(),
                  style: LC.mono(size: 8, color: LC.cyan)),
            ],
          ]),
          if (job.resultSummary != null && job.resultSummary!.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(job.resultSummary!,
                style: LC.head(size: 10, color: LC.textFaint, spacing: 0.1),
                maxLines: 2,
                overflow: TextOverflow.ellipsis),
          ],
          if (job.status != 'delivered') ...[
            const SizedBox(height: 10),
            Row(children: [
              const Spacer(),
              SizedBox(
                height: 24,
                child: LCButton(
                  label: 'MARK DELIVERED',
                  icon: Icons.check_circle_outline,
                  small: true,
                  onPressed: onDeliver,
                ),
              ),
            ]),
          ],
        ],
      ),
    );
  }
}
