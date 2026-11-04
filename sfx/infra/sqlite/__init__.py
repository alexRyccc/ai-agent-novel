"""SQLite 端口实现（ARCH §7.3 难点 4 / §10.2）。

跨库可移植纪律（D-1~D-5，违反者 CR 打回）
----------------------------------------
- D-1：禁止 ``INSERT OR REPLACE`` / ``REPLACE INTO``（SQLite 方言）→ 显式
  ``SELECT`` 后 ``UPDATE``/``INSERT``；
- D-2：禁止 ``strftime`` / ``ifnull`` / ``group_concat`` 等非通用函数 → 日期分桶
  与聚合一律在 Python 侧完成；
- D-3：禁止 ``AUTOINCREMENT`` → 主键一律 uuidv7 字符串（时间有序）；
- D-4：``core/`` 层不得出现 SQL → 一律经本包的 Repository；
- D-5：时间一律 RFC3339 UTC 字符串由应用层生成（``_boot.now_rfc3339``），不用 SQL ``now()``。
"""

from __future__ import annotations
