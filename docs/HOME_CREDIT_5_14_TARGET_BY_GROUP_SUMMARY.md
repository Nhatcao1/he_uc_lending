# Home Credit 5.14: Target by Group

## Muc dich

Tinh so ho so va so ho so default theo tung nhom danh muc, tren du lieu da ma hoa.

Trong Home Credit, `TARGET = 1` la ho so default; `TARGET = 0` la khong default.

## Input mau

| Row | Education | TARGET |
| ---: | --- | ---: |
| 1 | Higher education | 0 |
| 2 | Secondary | 1 |
| 3 | Higher education | 1 |
| 4 | Higher education | 0 |
| 5 | Secondary | 0 |

Vi du truy van nhom `Higher education`.

## Chuan bi truoc ma hoa

Nguon du lieu chuyen category thanh vector 0/1 theo nhom dang duoc hoi:

    group_mask  = [1, 0, 1, 1, 0]
    target_mask = [0, 1, 1, 0, 0]

`group_mask[i] = 1` khi dong i thuoc nhom Higher education. `target_mask[i] = 1` khi dong i default. Cac vector duoc dong goi theo chunk/slot CKKS va ma hoa cung context va evaluation keys; khoa bi mat khong roi khoi moi truong tin cay.

Mask can thiet vi OpenFHE CKKS xu ly vector so, khong the tu doc chuoi category hoac chay pandas `groupby` tren ciphertext.

## Phep tinh tren HE Server

Server chi nhan ciphertext va thuc hien:

    encrypted_count = Sum(encrypted_group_mask)
    encrypted_default_count = Sum(encrypted_group_mask * encrypted_target_mask)

Voi vi du tren:

    count = 1 + 0 + 1 + 1 + 0 = 3
    default_count = 1*0 + 0*1 + 1*1 + 1*0 + 0*0 = 1

Phep nhan giu lai TARGET chi tai cac dong thuoc nhom dang truy van. `EvalMult` va `EvalSum` duoc thuc hien tren ciphertext CKKS; server khong thay gia tri category hay TARGET goc.

## Giai ma va output

Ben tin cay giai ma hai tong:

| Segment | Count | Default count | Default rate |
| --- | ---: | ---: | ---: |
| Higher education | 3 | 1 | 33.33% |

`default_rate = default_count / count`. Trong benchmark hien tai, phep chia va dinh dang ty le duoc thuc hien sau giai ma; phan tinh tong va tich co dieu kien la HE.

## Pham vi 5.14

Cung mot mau tinh ap dung cho cac phan 5.14.1 den 5.14.7: income type, family status, occupation, education, housing, organization va type of people accompanying. Khac nhau duy nhat la cot category va danh sach nhom can truy van.
