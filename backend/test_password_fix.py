#!/usr/bin/env python3
"""
测试密码加密修复
验证bcrypt 72字节长度限制问题是否已解决
"""
from auth.utils import get_password_hash, verify_password


def test_password_hash():
    """测试密码哈希功能"""
    print("开始测试密码加密修复...")
    print("=" * 60)
    
    # 测试1: 短密码（正常情况）
    short_password = "password123"
    print(f"测试1 - 短密码: {short_password}")
    short_hash = get_password_hash(short_password)
    print(f"  哈希值: {short_hash[:60]}...")
    short_verified = verify_password(short_password, short_hash)
    print(f"  验证结果: {'✅ 成功' if short_verified else '❌ 失败'}")
    print()
    
    # 测试2: 长密码（超过72字节）
    long_password = "a" * 100  # 100个字符
    print(f"测试2 - 长密码: {'a' * 20}... (共100个字符)")
    print(f"  密码长度: {len(long_password)} 字节")
    try:
        long_hash = get_password_hash(long_password)
        print(f"  哈希值: {long_hash[:60]}...")
        print("  加密结果: ✅ 成功 (无异常)")
        
        # 验证长密码
        long_verified = verify_password(long_password, long_hash)
        print(f"  验证结果: {'✅ 成功' if long_verified else '❌ 失败'}")
    except Exception as e:
        print(f"  加密结果: ❌ 失败 - {e}")
    print()
    
    # 测试3: 中文密码
    chinese_password = "你好世界1234567890abcdefghijklmnopqrstuvwxyz"
    print(f"测试3 - 中文密码: {chinese_password}")
    print(f"  密码长度: {len(chinese_password)} 字符")
    try:
        chinese_hash = get_password_hash(chinese_password)
        print(f"  哈希值: {chinese_hash[:60]}...")
        print("  加密结果: ✅ 成功 (无异常)")
        
        # 验证中文密码
        chinese_verified = verify_password(chinese_password, chinese_hash)
        print(f"  验证结果: {'✅ 成功' if chinese_verified else '❌ 失败'}")
    except Exception as e:
        print(f"  加密结果: ❌ 失败 - {e}")
    print()
    
    print("=" * 60)
    print("测试完成！")


if __name__ == "__main__":
    test_password_hash()
