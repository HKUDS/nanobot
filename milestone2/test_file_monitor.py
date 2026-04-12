"""
文件监控系统测试脚本

测试功能：
- 文件创建、修改、删除的监控
- 大小和行数变化检测
- 对话文件监控
- 日志记录功能
"""

import os
import time
import json
from pathlib import Path
from shared.file_monitor import FileMonitor, ConversationFileMonitor

def test_basic_file_monitoring():
    """测试基础文件监控功能"""
    print("=== 测试基础文件监控功能 ===")
    
    monitor = FileMonitor(log_dir="test_logs")
    test_file = "test_monitor.txt"
    
    # 清理之前的测试文件
    if os.path.exists(test_file):
        os.remove(test_file)
    
    # 1. 测试文件创建
    print("\n1. 测试文件创建...")
    with open(test_file, 'w', encoding='utf-8') as f:
        f.write("第一行内容\n第二行内容\n")
    
    change = monitor.check_changes(test_file)
    print(f"创建检测: {change.status}")
    print(f"文件大小: {change.new_snapshot.size} bytes")
    print(f"文件行数: {change.new_snapshot.lines}")
    
    # 2. 测试文件修改
    print("\n2. 测试文件修改...")
    time.sleep(0.5)  # 确保时间戳不同
    
    with open(test_file, 'a', encoding='utf-8') as f:
        f.write("第三行内容\n第四行内容\n第五行内容\n")
    
    change = monitor.check_changes(test_file)
    print(f"修改检测: {change.status}")
    print(f"大小变化: {change.size_delta:+d} bytes ({change.size_percent:+.1f}%)")
    print(f"行数变化: {change.lines_delta:+d}")
    
    # 3. 测试文件删除
    print("\n3. 测试文件删除...")
    time.sleep(0.5)
    
    os.remove(test_file)
    change = monitor.check_changes(test_file)
    print(f"删除检测: {change.status}")
    print(f"大小变化: {change.size_delta:+d} bytes")
    
    # 4. 测试文件统计
    print("\n4. 测试文件统计...")
    stats = monitor.get_file_stats(test_file)
    print(f"文件存在: {stats['exists']}")
    
    # 重新创建文件测试统计
    with open(test_file, 'w', encoding='utf-8') as f:
        f.write("测试统计\n")
    
    stats = monitor.get_file_stats(test_file)
    print(f"文件大小: {stats['size']} bytes")
    print(f"文件行数: {stats['lines']}")
    
    # 清理
    if os.path.exists(test_file):
        os.remove(test_file)

def test_conversation_monitoring():
    """测试对话文件监控功能"""
    print("\n\n=== 测试对话文件监控功能 ===")
    
    # 创建测试对话目录结构
    test_conv_id = "test_conv_001"
    test_workspace = Path("test_workspace")
    conv_dir = test_workspace / f"conv_{test_conv_id}"
    
    # 清理之前的测试目录
    if conv_dir.exists():
        import shutil
        shutil.rmtree(conv_dir)
    
    # 创建目录结构
    (conv_dir / "memory").mkdir(parents=True, exist_ok=True)
    
    # 创建测试文件
    trajectory_file = conv_dir / "trajectory.jsonl"
    memory_file = conv_dir / "memory" / "MEMORY.md"
    history_file = conv_dir / "conversation_history.json"
    
    # 初始化文件内容
    with open(trajectory_file, 'w', encoding='utf-8') as f:
        f.write('{"step": 1, "action": "test"}\n')
    
    with open(memory_file, 'w', encoding='utf-8') as f:
        f.write("# 测试记忆\n初始记忆内容\n")
    
    with open(history_file, 'w', encoding='utf-8') as f:
        json.dump({"messages": []}, f, ensure_ascii=False, indent=2)
    
    # 创建监控器（使用测试工作空间）
    monitor = ConversationFileMonitor(base_workspace=str(test_workspace))
    
    # 1. 初始监控
    print("\n1. 初始文件监控...")
    changes = monitor.monitor_conversation(test_conv_id)
    
    for file_path, change in changes.items():
        filename = Path(file_path).name
        print(f"{filename}: {change.status}")
    
    # 2. 修改文件并监控
    print("\n2. 修改文件并监控...")
    
    # 修改轨迹文件
    with open(trajectory_file, 'a', encoding='utf-8') as f:
        f.write('{"step": 2, "action": "updated"}\n')
    
    # 修改记忆文件
    with open(memory_file, 'a', encoding='utf-8') as f:
        f.write("\n新增记忆内容\n")
    
    time.sleep(0.5)
    changes = monitor.monitor_conversation(test_conv_id)
    
    for file_path, change in changes.items():
        if change.status != "unchanged":
            filename = Path(file_path).name
            print(f"{filename}: {change.status}")
            print(f"  大小变化: {change.size_delta:+d} bytes")
            print(f"  行数变化: {change.lines_delta:+d}")
    
    # 3. 测试对话统计
    print("\n3. 测试对话文件统计...")
    stats = monitor.get_conversation_stats(test_conv_id)
    
    for filename, stat in stats.items():
        if stat["exists"]:
            print(f"{filename}: {stat['size']} bytes, {stat['lines']} lines")
        else:
            print(f"{filename}: 不存在")
    
    # 4. 测试对话变化日志
    print("\n4. 测试对话变化日志...")
    monitor.log_conversation_changes(
        test_conv_id, 
        "test_action", 
        "测试对话文件变化监控"
    )
    
    # 清理测试目录
    if test_workspace.exists():
        import shutil
        shutil.rmtree(test_workspace)

def test_monitor_performance():
    """测试监控性能"""
    print("\n\n=== 测试监控性能 ===")
    
    monitor = FileMonitor()
    test_files = [f"perf_test_{i}.txt" for i in range(5)]
    
    # 创建测试文件
    for file_path in test_files:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write("性能测试内容\n" * 10)
    
    # 性能测试：监控多个文件
    import time
    
    start_time = time.time()
    
    for i in range(10):  # 模拟10次监控循环
        changes = monitor.monitor_files(test_files)
        
        # 修改文件以产生变化
        if i % 2 == 0:
            for file_path in test_files:
                with open(file_path, 'a', encoding='utf-8') as f:
                    f.write(f"更新内容 {i}\n")
    
    end_time = time.time()
    
    print(f"监控10次循环耗时: {end_time - start_time:.3f} 秒")
    print(f"平均每次监控耗时: {(end_time - start_time) / 10:.3f} 秒")
    
    # 清理
    for file_path in test_files:
        if os.path.exists(file_path):
            os.remove(file_path)

def test_log_parsing():
    """测试日志解析功能"""
    print("\n\n=== 测试日志解析功能 ===")
    
    monitor = FileMonitor(log_dir="test_logs")
    test_file = "log_test.txt"
    
    # 创建并修改文件产生日志
    with open(test_file, 'w', encoding='utf-8') as f:
        f.write("日志测试\n")
    
    monitor.check_changes(test_file)
    
    with open(test_file, 'a', encoding='utf-8') as f:
        f.write("修改内容\n")
    
    monitor.check_changes(test_file)
    
    # 读取并解析日志
    if monitor.change_log_file.exists():
        print("日志文件内容:")
        with open(monitor.change_log_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    try:
                        entry = json.loads(line)
                        print(f"- {entry['path']}: {entry['status']}")
                    except:
                        print("解析错误")
    
    # 测试历史查询
    history = monitor.get_change_history(test_file)
    print(f"\n{test_file} 的变化历史: {len(history)} 条记录")
    
    # 清理
    if os.path.exists(test_file):
        os.remove(test_file)

if __name__ == "__main__":
    print("文件监控系统测试开始...\n")
    
    try:
        test_basic_file_monitoring()
        test_conversation_monitoring()
        test_monitor_performance()
        test_log_parsing()
        
        print("\n✅ 所有测试完成！")
        
    except Exception as e:
        print(f"\n❌ 测试出错: {e}")
        import traceback
        traceback.print_exc()
    
    # 清理测试日志目录
    if os.path.exists("test_logs"):
        import shutil
        shutil.rmtree("test_logs")