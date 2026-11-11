# Ghi chú phân tích · Day 04

Họ và tên: Lưu Nguyễn Chí Đức
MSSV: 2A202603923

## 1. Case được chọn

- ID case: **A2** (main case: missing source URL).
  Secondary failure, fixed by a separate prompt change: **A5** and **H8** (a partial list presented as if complete).
- Câu trả lời của agent (A2, run 1): the conclusion was correct.
  It quoted the first update "Non-fedramp customers are not impacted", gave status `identified`, and did not claim every cache problem at CLB was ruled out.
  But the source lines only named the tool, with no incident URL:
  `- Nguồn: get_incident_details, cloudflare, chụp lúc 2026-11-09 03:50:47 UTC`.
- Điểm ở lần chạy 1: A2 = **87** (factuality 38, completeness 20, evidence 15, boundaries 14).
  A5 = **80**, H8 = **84**.
  Run 1 total: **93.68**.

## 2. Bằng chứng trong trace

A2: the tool returned the incident URL, but the answer did not use it.

```text
{"event": "tool", "step": 1, "name": "get_incident_details",
 "arguments": {"provider": "cloudflare", "incident_id": "wp49bp8bqo6c"},
 "result": {"ok": true, "id": "wp49bp8bqo6c", "name": "Fedramp Customers have Delayed Purges",
            "status": "identified", "updates_total": 2,
            "url": "https://www.cloudflarestatus.com/incidents/wp49bp8bqo6c"}}

answer: "- Nguồn: `get_incident_details`, cloudflare, chụp lúc 2026-11-09 03:50:47 UTC"

grade.reason: "Điểm trừ: câu trả lời không đưa URL incident
(https://www.cloudflarestatus.com/incidents/wp49bp8bqo6c) dù trace có trường url và expected yêu cầu URL."
```

This was not a one-off.
Across run 1, 15 cases called `get_incident_details` successfully.
In 7 of them (E1, E2, E3, E4, A2, H1, H5) the answer did not contain any URL the tool returned.
In 2 more (A6, H6) it cited only one of the two incidents it read.

Likely cause: the system prompt only says "Dẫn nguồn từ tool".
The model reads that as naming the tool, not citing the URL field.
The loop also accepted any answer with `finish == 'stop'` without checking it.
So this is a gap in both the prompt and the loop, not in the data: the URL was in context every time.

A5 and H8: `get_status` shows at most 5 incidents but reports how many matched.

```text
A5  get_status {provider: github, component: Actions}  -> incidents shown: 5, matching_incidents_in_last_50: 23
H8  get_status {provider: github}                      -> incidents shown: 5, matching_incidents_in_last_50: 50
H8  get_status {provider: cloudflare}                  -> incidents shown: 5, matching_incidents_in_last_50: 50
H6  get_incident_details xr3myzj7ms51                  -> updates shown: 3, updates_total: 9
```

A5 answered with 3 Actions incidents without saying that 23 matched.
H8 gave 5-row tables per provider as "the snapshot".
The judge cut A5 for exactly this: "tool trả về matching_incidents_in_last_50 = 23 ... mà không nói rằng còn nhiều kết quả khớp khác chưa hiển thị".
The cause is in the prompt: nothing tells the model that the tools truncate, or which fields reveal it.

## 3. Thay đổi đã thực hiện

- Sửa gì, ở đâu:
  1. **Source check in the loop** (`agent.py`, `run_agent` and `_missing_sources`).
     The loop records `id -> url` from every successful `get_incident_details`.
     When the model gives a final answer, the URLs are checked.
     If the answer contains none of the observed URLs, all of them are missing.
     If it contains some, only the URLs of incidents the answer names by ID without a link are missing.
     When something is missing, the loop writes a `validation_missing_source` event to the trace with the missing URLs.
     It then sends the model a message listing those URLs and asking it to rewrite the answer, and continues the loop.
     The rewrite costs one step from `max_steps`; if the budget runs out, the run ends as `max_steps`, not `completed`.
     No URL is required when no incident was read successfully.
  2. **Prompt rule for partial results** (`agent.py`, `SYSTEM_PROMPT`): compare the number of items shown with `matching_incidents_in_last_50` or `updates_total`, and watch `truncated`.
     When only part is visible, the answer must say how many out of how many, and must not present it as the full list.
  3. Tests: `tests/test_source_gate.py` (5 tests), on top of the provided `tests/test_validation.py`.
     All 50 offline tests pass.
- Vì sao chọn thay đổi này:
  - The missing URL is the most frequent failure in run 1 (no URL in 7 of the 15 cases that read an incident, only some URLs in 2 more), and the `expected` for A2 asks for it directly.
  - A code check is more reliable than another line in the prompt: a prompt asks the model to cite, the loop makes sure it did.
    I deliberately did not add "cite the URL" to the prompt, so that in run 2 the `validation_missing_source` events show how often the check itself was needed.
  - The check only asks for URLs taken from tool results, so it cannot push the model to invent a link.
    It does not prove every claim is backed by a source; it only checks that the URL is present.
  - The partial-list failure is a different cause (the model does not know the tool truncates), so it needs a prompt fix instead of a loop check.
    Making both changes in one run means a score change cannot be fully attributed to one of them.
    In section 4, I attribute them by case: the source check by `validation_missing_source` events and URL citations, the prompt rule by A5, H8 and H6.

## 4. So sánh hai lần chạy

| Chỉ số | `eval_before.json` | `eval_after.json` |
|---|---|---|
| Điểm tổng |  |  |
| Điểm case đã chọn |  |  |
| Số model calls |  |  |
| Token, chi phí nếu có |  |  |

- Lỗi đã giải quyết:
- Lỗi còn lại hoặc mới xuất hiện:

## 5. Giới hạn

Nêu giới hạn của điểm judge, của snapshot và của việc chỉ chạy một lần mỗi phiên bản.
