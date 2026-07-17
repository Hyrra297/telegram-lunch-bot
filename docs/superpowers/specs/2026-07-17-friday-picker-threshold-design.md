# Ngưỡng phân công người lấy bún đậu thứ 6

## Mục tiêu

Thay đổi việc phân công lúc chốt vote 10:30 thứ 6 dựa trên số người đã đặt:

- Từ 1 đến 7 suất: phân công 1 người đi lấy bún đậu.
- Từ 8 suất trở lên: phân công 2 người khác nhau đi lấy bún đậu.
- Không có người đặt: giữ nguyên hành vi hiện tại, thông báo không có ai đặt.

Mỗi người đã đặt được tính là một suất. Số suất được lấy từ danh sách voter tại thời điểm chốt vote.

## Thiết kế

Giữ nguyên mô hình dữ liệu hiện tại để thay đổi có phạm vi nhỏ:

- Người lấy thứ nhất lưu trong `daily_votes.picker_user_id`.
- Khi đủ ngưỡng 8 suất, người lấy thứ hai lưu trong `daily_votes.returner_user_id`, đúng với cách luồng thứ 6 hiện tại đang sử dụng cột này.
- Khi dưới ngưỡng, `returner_user_id` được lưu là `NULL`.

Luồng `_scheduled_announce_roles` tiếp tục chọn người đầu tiên bằng `pick_next_fetcher`. Chỉ khi ngày là thứ 6 và `len(voters) >= 8`, luồng mới chọn người thứ hai bằng cơ chế vòng xoay hiện có, bảo đảm người thứ hai khác người thứ nhất nếu có đủ ứng viên.

Tin nhắn phân công:

- Dưới 8 suất: `🛵 @A đi lấy bún đậu`.
- Từ 8 suất: `🛵 @A và @B đi lấy bún đậu`.

## Phạm vi không thay đổi

- Thứ 2 đến thứ 5 vẫn phân công một người lấy cơm và một người trả hộp.
- Thứ 6 không phân công trả hộp.
- Thứ 6 không tính tiền lúc 10:30; job `friday_settle` lúc 15:00 vẫn chốt chi phí.
- Không thêm cột hoặc migration cơ sở dữ liệu.
- Các lệnh phân công thủ công không nằm trong phạm vi thay đổi này.

## Kiểm thử

Triển khai theo TDD với các trường hợp biên:

1. Thứ 6 có 7 voter: chỉ có `picker_user_id`, `returner_user_id` là `NULL`, tin nhắn chỉ nêu một người lấy.
2. Thứ 6 có 8 voter: có hai ID khác nhau, tin nhắn nêu hai người cùng đi lấy.
3. Ngày thường có nhiều voter: hành vi người lấy cơm/người trả hộp không đổi.
4. Thứ 6 vẫn không chốt chi phí lúc 10:30.
