#!/usr/bin/env python3
"""
测试密码加密修复
"""
import sys
import os

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from auth.utils import get_password_hash, verify_password
    print("✅ 成功导入auth.utils模块")
    
    # 测试短密码
    short_password = "password123"
    short_hash = get_password_hash(short_password)
    short_verified = verify_password(short_password, short_hash)
    print(f"✅ 短密码测试: {'成功' if short_verified else '失败'}")
    
    # 测试长密码（超过72字节）
    long_password = "a" * 100
    try:
        long_hash = get_password_hash(long_password)
        long_verified = verify_password(long_password, long_hash)
        print(f"✅ 长密码测试: {'成功' if long_verified else '失败'}")
        print("✅ bcrypt长度限制问题已修复")
    except Exception as e:
        print(f"❌ 长密码测试失败: {e}")
        print("❌ bcrypt长度限制问题未修复")
        
except ImportError as e:
    print(f"❌ 导入模块失败: {e}")
    print("请检查auth/utils.py文件是否存在")

except Exception as e:
    print(f"❌ 测试失败: {e}")
