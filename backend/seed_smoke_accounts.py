"""
冒烟测试种子账号:检查/创建(纯增量,不破坏现有数据)

用途:让 V0907 前端契约冒烟(node scripts/smoke-test.js,默认账号 admin/李小明/李秀英/志愿者,
密码 123456)能在你的真实服务器上跑起来。

安全默认(可放心执行):
- 账号已存在 → 不覆盖,仅校验其密码是否为 123456 并报告(密码不同则用 --pwd 运行冒烟)
- 只新增缺失的:账号、李秀英档案、李小明↔李秀英绑定
- 不动任何已有账号/档案/照片/绑定
可选增补(测试数据,明确标注,可 --undo 撤):
- --create-elder:库里没有"李秀英"档案时新建一个(否则冒烟老人段无对象)
- --photos=N:李秀英名下无照片时生成 N 张跨年演示照片(时间轴/聚合断言需要;真数据已够则跳过)
- --reset-existing:已存在账号密码≠123456 时强制重置(慎用)

用法(服务器,backend 目录):
    python3 seed_smoke_accounts.py                # 只建缺的账号/档案/绑定
    python3 seed_smoke_accounts.py --create-elder --photos=24
    python3 seed_smoke_accounts.py --undo         # 撤掉本脚本新建的演示数据(不动已有数据)
之后在服务器上跑:
    cd 交付包V0907 && node scripts/smoke-test.js --base=http://localhost:8000/api
"""
import sys
import os
import io
import uuid
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text  # noqa: E402
from models.database import SessionLocal  # noqa: E402
from models.user import User, UserRole  # noqa: E402
from models.elderly import Elderly  # noqa: E402
from models.photo import Photo  # noqa: E402
from models.elderly_child import elderly_child  # noqa: E402
from utils.auth import get_password_hash, verify_password  # noqa: E402
from utils.timefmt import now_local  # noqa: E402

PWD = "123456"
CREATED = {"users": [], "elderly": [], "bindings": [], "photos": 0, "reset": []}
DB = SessionLocal()

try:
    DB.execute(text("SELECT 1"))
    print("数据库连接 OK")
except Exception as e:
    print("数据库连接失败:", e)
    print("请确认 config.py 指向的 DB 配置(.env)正确、MariaDB 在运行。")
    sys.exit(1)


def get_user(username):
    return DB.query(User).filter(User.username == username).first()


def ensure_user(username, role, name=None, phone=None, undo=False):
    u = get_user(username)
    if u:
        if u.role != role:
            print(f"  账号 {username} 已存在但 role={u.role}(期望 {role}),未改动")
        elif verify_password(PWD, u.password_hash):
            print(f"  账号 {username}({role}) 已存在且密码为 {PWD} ✓")
        else:
            print(f"  ⚠️ 账号 {username} 已存在但密码≠{PWD}:跑冒烟请加 --pwd 参数,或用 --reset-existing 重置")
        return u
    if undo:
        return None
    u = User(username=username, password_hash=get_password_hash(PWD), role=UserRole(role),
             name=name or username, phone=phone)
    DB.add(u)
    DB.commit()
    DB.refresh(u)
    CREATED["users"].append(u.id)
    print(f"  创建账号 {username}({role}, 密码 {PWD}) id={u.id}")
    return u


def ensure_elder_xiuying(account, undo=False):
    e = DB.query(Elderly).filter(Elderly.name == "李秀英").first()
    if e:
        print(f"  李秀英档案已存在 id={e.id} ✓")
        return e
    if undo or not account:
        return None
    e = Elderly(name="李秀英", age=82, gender="女", contact_info="13900005678",
                guardian_contact="", address="", created_by=account.id)
    DB.add(e)
    DB.commit()
    DB.refresh(e)
    CREATED["elderly"].append(e.id)
    print(f"  创建演示档案 李秀英 id={e.id}(冒烟老人段用)")
    return e


def ensure_binding(child, elder, undo=False):
    if not child or not elder:
        return
    row = DB.execute(elderly_child.select().where(
        elderly_child.c.child_id == child.id,
        elderly_child.c.elderly_id == elder.id,
    )).first()
    if row:
        print(f"  李小明↔李秀英 绑定已存在 ✓")
        return
    if undo:
        return
    DB.execute(elderly_child.insert().values(
        child_id=child.id, elderly_id=elder.id, relationship="儿子", created_at=now_local()))
    DB.commit()
    CREATED["bindings"].append((child.id, elder.id))
    print(f"  创建绑定 李小明(id={child.id}) → 李秀英(id={elder.id}, 关系:儿子)[演示]")
    return


def ensure_photos(elder, count):
    have = DB.query(Photo).filter(Photo.elderly_id == elder.id).count()
    if have > 0:
        print(f"  李秀英名下已有 {have} 张照片,跳过演示照片生成 ✓")
        return
    if count <= 0:
        print("  李秀英名下无照片:冒烟时间轴/聚合断言将 FAIL(可用 --photos=N 生成演示照片)")
        return
    # 用 PIL 生成纯色小图(确定性),跨 2025-2026 的多个月份,模拟时间轴数据
    try:
        from PIL import Image
    except Exception:
        print("  PIL 不可用,跳过照片生成")
        return
    colors = [(180, 60, 60), (60, 120, 180), (90, 160, 90), (200, 150, 60), (150, 90, 170)]
    base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
    thumbs_dir = os.path.join(base_dir, "thumbs")
    os.makedirs(base_dir, exist_ok=True)
    os.makedirs(thumbs_dir, exist_ok=True)
    days = [3, 8, 15, 21, 27]
    months_pool = []
    for y in (2025, 2026):
        for m in range(1, 13):
            months_pool.append((y, m))
    # 尽量均匀铺开,让"最新照片"落在 2026 年初附近
    months_pool.sort(reverse=True)
    account = DB.query(User).filter(User.username == "李秀英").first()
    if not account:
        account = DB.query(User).filter(User.role == "admin").first()
    if not account:
        print("  找不到可用的上传者账号,跳过照片生成")
        return
    for i in range(count):
        y, m = months_pool[i % len(months_pool)]
        d = days[i % len(days)]
        name = f"demo_{uuid.uuid4().hex}.png"
        img = Image.new("RGB", (400, 300), colors[i % len(colors)])
        img.save(os.path.join(base_dir, name))
        img.thumbnail((200, 200))
        img.save(os.path.join(thumbs_dir, f"thumb_{name}"))
        ts = datetime(y, m, d, 9 + i % 10, (i * 13) % 60)
        p = Photo(
            elderly_id=elder.id,
            volunteer_id=account.id,
            original_path=name,
            thumbnail_path=f"thumbs/thumb_{name}",
            note=f"演示照片 {i + 1}",
            file_size=1024 * 50,
            width=400,
            height=300,
            upload_time=ts,
        )
        DB.add(p)
        CREATED["photos"] += 1
    DB.commit()
    print(f"  生成 {count} 张跨年演示照片[测试数据,可 --undo 撤销]")


def undo_all():
    """只清除可辨识的演示数据(绝不动账号,避免误伤既有数据):
    1. 演示照片 note='演示照片 %'
    2. 演示档案 李秀英(phone=13900005678 且创建者是李秀英账号)及其绑定
    """
    # 演示照片
    del_photos = DB.execute(text("DELETE FROM photos WHERE note LIKE '演示照片 %'"))
    print(f"  清除演示照片 {del_photos.rowcount if del_photos.rowcount else 0} 张")
    # 演示档案 + 其绑定(仅当确为本脚本建的:创建者是李秀英账号且手机号是演示号)
    elder_acct = get_user("李秀英")
    e = DB.query(Elderly).filter(
        Elderly.name == "李秀英", Elderly.contact_info == "13900005678"
    ).first()
    if e and elder_acct and e.created_by == elder_acct.id:
        DB.execute(elderly_child.delete().where(elderly_child.c.elderly_id == e.id))
        DB.execute(text("DELETE FROM photos WHERE elderly_id = :e"), {"e": e.id})
        DB.delete(e)
        print(f"  清除演示档案 李秀英 id={e.id}(含其照片与绑定)")
    DB.commit()
    print("撤销完成。账号(admin/李小明/李秀英/志愿者)保留,如需删除请人工在库里操作。")


if __name__ == "__main__":
    args = sys.argv[1:]
    undo = "--undo" in args
    create_elder = "--create-elder" in args
    photos = 0
    for a in args:
        if a.startswith("--photos="):
            photos = int(a.split("=", 1)[1])
    if "--reset-existing" in args:
        for u in DB.query(User).filter(User.username.in_(["admin", "李小明", "李秀英", "志愿者"])).all():
            if not verify_password(PWD, u.password_hash):
                u.password_hash = get_password_hash(PWD)
                CREATED["reset"].append(u.username + "(密码)")
            if u.is_active is False:
                u.is_active = True
                CREATED["reset"].append(u.username + "(重新激活)")
        DB.commit()
        print("已重置/激活:", CREATED["reset"] if CREATED["reset"] else "无(四账号本就密码正确且激活)")

    if undo:
        undo_all()
        sys.exit(0)

    print("==> 账号(密码 123456,均已存在则跳过)")
    admin = ensure_user("admin", "admin")
    vol = ensure_user("志愿者", "volunteer", name="张志愿者", phone="13600003333")
    xiaoming = ensure_user("李小明", "children", phone="13800000001")

    print("==> 李秀英(冒烟老人端与时间轴依赖)")
    elder_acct = ensure_user("李秀英", "elder", phone="13900005678")
    if create_elder:
        xiuying = ensure_elder_xiuying(elder_acct)
    else:
        xiuying = DB.query(Elderly).filter(Elderly.name == "李秀英").first()
        if xiuying:
            print(f"  李秀英档案已存在 id={xiuying.id} ✓")
        else:
            print("  库中无'李秀英'档案:冒烟老人段无法测(可 --create-elder 补一个演示档案)")

    print("==> 李小明 ↔ 李秀英 绑定(家属端时间轴依赖)")
    if xiuying:
        ensure_binding(xiaoming, xiuying)
    else:
        print("  跳过绑定(无李秀英档案)")

    print("==> 演示照片(可选)")
    if xiuying:
        ensure_photos(xiuying, photos)

    print("\n完成。下一步(服务器上):")
    print("  cd <交付包V0907> && node scripts/smoke-test.js --base=http://localhost:8000/api")
    print("  如需真实数据上验证而演示账号密码不同,给 --pwd 覆盖:")
    print("  node scripts/smoke-test.js --base=http://localhost:8000/api --pwd=你的admin密码")
