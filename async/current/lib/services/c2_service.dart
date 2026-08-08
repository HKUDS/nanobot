import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

// ── MODELS ────────────────────────────────────────

enum AgentStatus { unknown, online, offline, error, starting, stopping }

enum McpStatus { online, offline, error, unknown }

enum ConnMode { local, azure, oracle, hp, disconnected }

class McpServer {
  final String name;
  final McpStatus status;
  final String category;
  final int toolCount;
  final String lastUsed;
  final String? errorMsg;
  bool enabled;

  McpServer(
      {required this.name,
      required this.status,
      required this.category,
      required this.toolCount,
      required this.lastUsed,
      this.errorMsg,
      this.enabled = true});

  factory McpServer.fromJson(Map<String, dynamic> j) => McpServer(
        name: j['name'] ?? '',
        status: _parseStatus(j['status']),
        category: j['category'] ?? 'UNKNOWN',
        toolCount: j['tool_count'] ?? 0,
        lastUsed: j['last_used'] ?? 'NEVER',
        errorMsg: j['error'],
        enabled: j['enabled'] ?? true,
      );

  static McpStatus _parseStatus(String? s) => switch (s) {
        'online' => McpStatus.online,
        'offline' => McpStatus.offline,
        'error' => McpStatus.error,
        _ => McpStatus.unknown,
      };
}

class SystemStatus {
  final AgentStatus agentStatus;
  final String activeTask;
  final double serverCpu;
  final double serverRam;
  final double serverDisk;
  final String serverUptime;
  final List<McpServer> mcpServers;
  final String timestamp;
  final Map<String, dynamic> taskStats;
  final Map<String, dynamic> awsStats;

  double get oracleCpu => serverCpu;
  double get oracleRam => serverRam;
  double get oracleDisk => serverDisk;
  String get oracleUptime => serverUptime;
  double get hpCpu => serverCpu;
  double get hpRam => serverRam;
  int get awsLambdaToday => awsStats['lambda_today']?.toInt() ?? 0;
  int get sqsDepth => awsStats['sqs_depth']?.toInt() ?? 0;
  int get dbItems => awsStats['db_items']?.toInt() ?? 0;

  const SystemStatus({
    this.agentStatus = AgentStatus.unknown,
    this.activeTask = 'IDLE',
    this.serverCpu = 0,
    this.serverRam = 0,
    this.serverDisk = 0,
    this.serverUptime = '--',
    this.mcpServers = const [],
    this.timestamp = '--',
    this.taskStats = const {},
    this.awsStats = const {},
  });

  factory SystemStatus.fromJson(Map<String, dynamic> j) {
    final server = j['server'] ?? j['oracle'] ?? {};
    return SystemStatus(
      agentStatus: _parseAgent(j['agent_status']),
      activeTask: j['active_task'] ?? 'IDLE',
      serverCpu: (server['cpu_pct'] ?? 0).toDouble(),
      serverRam: (server['ram_pct'] ?? 0).toDouble(),
      serverDisk: (server['disk_pct'] ?? 0).toDouble(),
      serverUptime: server['uptime'] ?? '--',
      mcpServers: (j['mcp_servers'] as List? ?? [])
          .map((e) => McpServer.fromJson(e))
          .toList(),
      timestamp: j['timestamp'] ?? '--',
      taskStats: j['task_stats'] ?? {},
      awsStats: j['aws'] ?? {},
    );
  }

  SystemStatus copyWithPush(Map<String, dynamic> j) {
    final server = j['server'] ?? {};
    return SystemStatus(
      agentStatus: j['agent_status'] != null
          ? _parseAgent(j['agent_status'])
          : agentStatus,
      activeTask: j['active_task'] ?? activeTask,
      serverCpu: (server['cpu_pct'] ?? serverCpu).toDouble(),
      serverRam: (server['ram_pct'] ?? serverRam).toDouble(),
      serverDisk: (server['disk_pct'] ?? serverDisk).toDouble(),
      serverUptime: server['uptime'] ?? serverUptime,
      mcpServers: mcpServers,
      timestamp: j['timestamp'] ?? timestamp,
      taskStats: j['task_stats'] ?? taskStats,
      awsStats: j['aws'] ?? awsStats,
    );
  }

  static AgentStatus _parseAgent(String? s) => switch (s) {
        'online' => AgentStatus.online,
        'offline' => AgentStatus.offline,
        'error' => AgentStatus.error,
        'starting' => AgentStatus.starting,
        'stopping' => AgentStatus.stopping,
        _ => AgentStatus.unknown,
      };

  int get mcpOnline =>
      mcpServers.where((m) => m.status == McpStatus.online).length;
  int get mcpTotal => mcpServers.length;
}

// ── C2 SERVICE ────────────────────────────────────

class C2Service extends ChangeNotifier {
  static const _storage = FlutterSecureStorage();
  static const _keyToken = 'c2_jwt_token';
  static const _keyOracle = 'oracle_host';
  static const _keyHp = 'hp_host';
  static const _keyAzure = 'azure_host';

  // Azure is primary, Oracle is secondary, HP is local fallback.
  String _oracleHost = '';
  String _hpHost = '';
  String _azureHost = '';
  String _token = '';

  ConnMode _connMode = ConnMode.disconnected;
  SystemStatus _status = const SystemStatus();
  bool _loading = false;
  String? _error;

  List<String> _logBuffer = [];
  int _logCursor = 0;

  bool _streaming = false;
  String _streamBuffer = '';
  String _streamModelName = '';

  WebSocketChannel? _wsChannel;
  StreamSubscription? _wsSub;
  Timer? _reconnectTimer;

  // ── Getters ──
  ConnMode get connMode => _connMode;
  SystemStatus get status => _status;
  bool get loading => _loading;
  String? get error => _error;
  List<String> get logBuffer => List.unmodifiable(_logBuffer);
  bool get connected => _connMode != ConnMode.disconnected;
  bool get streaming => _streaming;
  String get streamBuffer => _streamBuffer;
  String get streamModel => _streamModelName;
  String get token => _token;
  String get azureHost => _azureHost;
  String get oracleHost => _oracleHost;
  String get hpHost => _hpHost;

  Future<void> fetchStatus() async {
    if (!connected) await connect();
  }

  String get activeHost => switch (_connMode) {
        ConnMode.local => '127.0.0.1:18790',
        ConnMode.azure => _azureHost,
        ConnMode.oracle => _oracleHost,
        ConnMode.hp => _hpHost,
        _ => '',
      };

  String get activeBaseUrl => _baseUrlForHost(activeHost);

  String get connLabel => switch (_connMode) {
        ConnMode.local => 'LOCAL',
        ConnMode.azure => 'AZURE',
        ConnMode.oracle => 'ORACLE',
        ConnMode.hp => 'HP-LOCAL',
        _ => 'OFFLINE',
      };

  String get serverLabel => switch (_connMode) {
        ConnMode.local => 'LOCAL DESKTOP // PRIMARY',
        ConnMode.azure => 'AZURE VM // FALLBACK NODE',
        ConnMode.oracle => 'ORACLE ARM // FALLBACK NODE',
        ConnMode.hp => 'HP NODE // FALLBACK NODE',
        _ => 'NO CONNECTION',
      };

  String _normalizeHost(String host) {
    final trimmed = host.trim();
    if (trimmed.isEmpty) return '';
    return trimmed
        .replaceFirst(RegExp(r'^https?://', caseSensitive: false), '')
        .replaceAll(RegExp(r'/$'), '');
  }

  bool _isLocalHost(String host) {
    if (host.isEmpty) return false;
    final raw = _normalizeHost(host).split(':').first.toLowerCase();
    if (raw == 'localhost' || raw == '127.0.0.1' || raw == '::1') return true;
    if (raw.startsWith('10.')) return true;
    if (raw.startsWith('192.168.')) return true;
    final parts = raw.split('.');
    if (parts.length == 4 && parts.first == '172') {
      final second = int.tryParse(parts[1]) ?? -1;
      return second >= 16 && second <= 31;
    }
    return false;
  }

  String _schemeForHost(String host) => _isLocalHost(host) ? 'http' : 'https';

  String _baseUrlForHost(String host) {
    final normalized = _normalizeHost(host);
    if (normalized.isEmpty) return '';
    return '${_schemeForHost(normalized)}://$normalized';
  }

  String _wsBaseUrlForHost(String host) {
    final normalized = _normalizeHost(host);
    if (normalized.isEmpty) return '';
    return '${_schemeForHost(normalized) == 'https' ? 'wss' : 'ws'}://$normalized';
  }

  // ── Init ──
  Future<void> init() async {
    _token = await _storage.read(key: _keyToken) ?? '';
    _oracleHost = _normalizeHost(await _storage.read(key: _keyOracle) ?? '');
    _hpHost = _normalizeHost(await _storage.read(key: _keyHp) ?? '');
    _azureHost = _normalizeHost(await _storage.read(key: _keyAzure) ?? '');
    // Always attempt connect (especially for LOCAL mode which bypasses token)
    await connect();
  }

  Future<void> saveCredentials({
    required String oracleHost,
    required String hpHost,
    required String token,
    String azureHost = '',
  }) async {
    _oracleHost = _normalizeHost(oracleHost);
    _hpHost = _normalizeHost(hpHost);
    _azureHost = _normalizeHost(azureHost);
    _token = token;
    await _storage.write(key: _keyOracle, value: _oracleHost);
    await _storage.write(key: _keyHp, value: _hpHost);
    await _storage.write(key: _keyAzure, value: _azureHost);
    await _storage.write(key: _keyToken, value: token);
    await connect();
  }

  // ── Connection — Local first, then Azure, Oracle, HP fallback ──
  Future<void> connect() async {
    _loading = true;
    _error = null;
    notifyListeners();
    _wsChannel?.sink.close();

    if (await _tryConnect('127.0.0.1:18790')) {
      _connMode = ConnMode.local;
    } else if (_azureHost.isNotEmpty && await _tryConnect(_azureHost)) {
      _connMode = ConnMode.azure;
    } else if (_oracleHost.isNotEmpty && await _tryConnect(_oracleHost)) {
      _connMode = ConnMode.oracle;
    } else if (_hpHost.isNotEmpty && await _tryConnect(_hpHost)) {
      _connMode = ConnMode.hp;
    } else {
      _connMode = ConnMode.disconnected;
      _error = 'ALL SERVERS UNREACHABLE';
    }

    _loading = false;
    notifyListeners();
    if (connected) _startWebSocket();
  }

  Future<bool> _tryConnect(String host) async {
    try {
      final baseUrl = _baseUrlForHost(host);
      final r = await http.get(
        Uri.parse('$baseUrl/health'),
        headers: {'Authorization': 'Bearer $_token'},
      ).timeout(const Duration(seconds: 5));
      return r.statusCode == 200;
    } catch (_) {
      return false;
    }
  } // ── WebSocket — push on change ──

  void _startWebSocket() {
    _wsSub?.cancel();
    _wsChannel?.sink.close();
    try {
      _wsChannel = WebSocketChannel.connect(
        Uri.parse(
            '${_wsBaseUrlForHost(activeHost)}/status/stream?token=$_token'),
      );
      _wsSub = _wsChannel!.stream.listen(
        _handleWsMessage,
        onError: (_) => _scheduleReconnect(),
        onDone: () => _scheduleReconnect(),
      );
    } catch (_) {
      _scheduleReconnect();
    }
  }

  void _handleWsMessage(dynamic raw) {
    try {
      final j = jsonDecode(raw as String) as Map<String, dynamic>;
      final type = j['type'] as String?;
      if (type == 'ping') return;
      if (type == 'status') {
        final data = j['data'] as Map<String, dynamic>?;
        if (data != null) {
          _status = j['full'] == true
              ? SystemStatus.fromJson(data)
              : _status.copyWithPush(data);
        }
        final newLogs = j['logs'] as List?;
        if (newLogs != null && newLogs.isNotEmpty) {
          for (final line in newLogs) {
            _logBuffer.add(line.toString());
          }
          if (_logBuffer.length > 500) {
            _logBuffer = _logBuffer.sublist(_logBuffer.length - 500);
          }
          _logCursor = j['log_cursor'] as int? ?? _logCursor;
        }
        notifyListeners();
      }
    } catch (_) {}
  }

  void _scheduleReconnect() {
    _reconnectTimer?.cancel();
    _reconnectTimer = Timer(const Duration(seconds: 15), () {
      if (!connected) {
        connect();
      } else {
        _startWebSocket();
      }
    });
  }

  // ── NVIDIA Streaming ──
  Future<void> streamPrompt({
    required String prompt,
    String? modelOverride,
    String? taskType,
    void Function(String token)? onToken,
    void Function(String model, String taskId)? onDone,
    void Function(String error)? onError,
  }) async {
    if (!connected) return;
    _streaming = true;
    _streamBuffer = '';
    notifyListeners();
    try {
      final request =
          http.Request('POST', Uri.parse('$activeBaseUrl/nvidia/stream'));
      request.headers['Authorization'] = 'Bearer $_token';
      request.headers['Content-Type'] = 'application/json';
      request.body = jsonEncode({
        'prompt': prompt,
        'model_override': modelOverride,
        'task_type': taskType,
        'stream': true,
      });
      final response = await request.send();
      if (response.statusCode != 200) {
        _streaming = false;
        notifyListeners();
        onError?.call('HTTP ${response.statusCode}');
        return;
      }
      await for (final chunk in response.stream.transform(utf8.decoder)) {
        for (final line in chunk.split('\n')) {
          if (!line.startsWith('data: ')) continue;
          final jsonStr = line.substring(6).trim();
          if (jsonStr.isEmpty) continue;
          try {
            final j = jsonDecode(jsonStr) as Map<String, dynamic>;
            if (j['done'] == true) {
              _streaming = false;
              _streamModelName = j['model'] as String? ?? '';
              notifyListeners();
              onDone?.call(_streamModelName, j['task_id'] as String? ?? '');
              if (j['error'] != null) onError?.call(j['error'].toString());
            } else {
              final t = j['token'] as String? ?? '';
              _streamBuffer += t;
              notifyListeners();
              onToken?.call(t);
            }
          } catch (_) {}
        }
      }
    } catch (e) {
      _streaming = false;
      notifyListeners();
      onError?.call(e.toString());
    }
  }

  void clearStreamBuffer() {
    _streamBuffer = '';
    _streaming = false;
    notifyListeners();
  }

  // ── API calls ──
  Future<bool> agentStart() => _post('/agent/start');
  Future<bool> agentStop() => _post('/agent/stop');
  Future<bool> agentKill() => _post('/agent/kill');
  Future<bool> agentRestart() async {
    await agentStop();
    await Future.delayed(const Duration(seconds: 2));
    return agentStart();
  }

  Future<bool> agentCommand(String cmd, {String priority = 'normal'}) async {
    final r = await _postBody(
        '/agent/command', {'command': cmd, 'priority': priority});
    return r != null && r.statusCode == 200;
  }

  Future<bool> mcpToggle(String name, bool enabled) async {
    final r =
        await _postBody('/mcp/servers/$name/toggle', {'enabled': enabled});
    if (r != null && r.statusCode == 200) {
      final idx = _status.mcpServers.indexWhere((m) => m.name == name);
      if (idx >= 0) _status.mcpServers[idx].enabled = enabled;
      notifyListeners();
      return true;
    }
    return false;
  }

  Future<bool> mcpRestart(String name) => _post('/mcp/servers/$name/restart');

  Future<bool> _post(String path) async {
    try {
      final r = await http.post(
        Uri.parse('$activeBaseUrl$path'),
        headers: {'Authorization': 'Bearer $_token'},
      ).timeout(const Duration(seconds: 10));
      return r.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  Future<http.Response?> _postBody(String path, Map body) async {
    try {
      return await http
          .post(
            Uri.parse('$activeBaseUrl$path'),
            headers: {
              'Authorization': 'Bearer $_token',
              'Content-Type': 'application/json'
            },
            body: jsonEncode(body),
          )
          .timeout(const Duration(seconds: 30));
    } catch (_) {
      return null;
    }
  }

  @override
  void dispose() {
    _reconnectTimer?.cancel();
    _wsSub?.cancel();
    _wsChannel?.sink.close();
    super.dispose();
  }
}

// v2.5.0 — active cloud URL for local agent offload
extension C2ServiceOracle on C2Service {
  String get cloudUrl {
    return activeBaseUrl;
  }

  String get oracleUrl {
    return cloudUrl;
  }
}
