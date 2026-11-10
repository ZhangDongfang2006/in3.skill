# language: zh-CN
功能: 响应信封归一与分页（envelope / pagination）
  作为 跑 IN3 查询的 agent
  我想 后端五花八门的信封被归一成单一 Page 形状
  以便 我不必按 endpoint 分叉解析、也不会把不可信 total 当真

  覆盖 Build-PRD 用户故事 13,14（issue #1 脊柱）— RTM #13, #14
  注：envelope.normalize 是纯函数，issue #1 的 TDD 内环用录制 fixture 最先把它转绿（最高 ROI）。

  场景大纲: RTM #13 — items 多形 unwrap
    假定 后端返回 <容器> 形信封
    当 envelope.normalize 归一
    那么 Page.items 取自 <容器> 字段

    例子:
      | 容器    |
      | content |
      | records |
      | items   |
      | list    |

  场景: RTM #14 — Spring Slice 无可信 total 时 total 置 None
    假定 后端返回的 total 缺失，或 total 小于本页 items 条数
    当 envelope.normalize 归一
    那么 Page.total 为 None
    并且绝不回退成 len(items)

  场景: RTM #14 — total 可信时原样取用
    假定 后端 totalElements 大于等于本页 items 条数
    当 envelope.normalize 归一
    那么 Page.total 等于该 totalElements

  场景: RTM #14 — has_next 优先 last 字段
    假定 后端响应含 last 字段
    当 envelope.normalize 归一
    那么 Page.has_next 等于 not last

  场景: RTM #14 — has_next 无 last 时用启发式
    假定 后端响应不含 last 字段
    当 envelope.normalize 归一
    那么 当本页 items 条数等于请求 size 时 has_next 为真，否则为假

  场景: RTM #14 — iterate_all 不按 total 循环、封顶标 truncated
    假定 一个分页数据源，total 不可信（None）
    当 pagination.iterate_all 翻页取全
    那么 翻页按 last/启发式判停、不按 total 计算次数
    并且达到封顶上限时早停并把结果标 truncated
