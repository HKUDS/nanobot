import sys
sys.path.insert(0, '.')
from bff.db import get_db

conn = get_db()

print("=== 悬赏数据库清理工具 ===\n")

print("1. 查看当前数据统计...")
bounty_count = conn.execute("SELECT COUNT(*) FROM bounties").fetchone()[0]
submission_count = conn.execute("SELECT COUNT(*) FROM submissions").fetchone()[0]
notification_count = conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]

print(f"   - 悬赏数量: {bounty_count}")
print(f"   - 提交数量: {submission_count}")
print(f"   - 通知数量: {notification_count}")

if bounty_count == 0:
    print("\n数据库已经是空的，无需清理。")
    conn.close()
    exit(0)

print("\n2. 查看悬赏详情...")
bounties = conn.execute("SELECT id, title, status, round, issuer_id FROM bounties").fetchall()
for b in bounties:
    print(f"   - [{b['status']}] {b['title'][:50]}... (round={b['round']}, issuer={b['issuer_id'][:8]})")

print("\n3. 开始清理数据...")

print("   - 删除 submissions 表中的数据...")
result = conn.execute("DELETE FROM submissions")
print(f"     删除了 {result.rowcount} 条提交记录")

print("   - 删除 notifications 表中的数据...")
result = conn.execute("DELETE FROM notifications")
print(f"     删除了 {result.rowcount} 条通知记录")

print("   - 删除 bounties 表中的数据...")
result = conn.execute("DELETE FROM bounties")
print(f"     删除了 {result.rowcount} 条悬赏记录")

conn.commit()

print("\n4. 清理后统计...")
bounty_count = conn.execute("SELECT COUNT(*) FROM bounties").fetchone()[0]
submission_count = conn.execute("SELECT COUNT(*) FROM submissions").fetchone()[0]
notification_count = conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
print(f"   - 悬赏数量: {bounty_count}")
print(f"   - 提交数量: {submission_count}")
print(f"   - 通知数量: {notification_count}")

print("\n✅ 悬赏数据库清理完成！")

conn.close()
