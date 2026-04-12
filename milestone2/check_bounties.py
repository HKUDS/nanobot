import sys
sys.path.insert(0, '.')
from bff.db import get_db
from datetime import datetime, timedelta

conn = get_db()
# 将所有 open 悬赏的 deadline 延长到 7 天后
new_deadline = datetime.now() + timedelta(days=7)
result = conn.execute("UPDATE bounties SET deadline = ? WHERE status = 'open'", (new_deadline,))
conn.commit()
print(f'已更新 {result.rowcount} 个悬赏的 deadline 到 {new_deadline}')