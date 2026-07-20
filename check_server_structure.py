#!/usr/bin/env python3
"""
检查服务器上的文件结构
"""
import os
import subprocess

def check_server_structure():
    """检查服务器上的文件结构"""
    print("检查服务器文件结构...")
    
    # 检查后端目录
    result = subprocess.run(
        ['ssh', 'root@36.112.162.239', 'ls -la /home/elder_photo_project/backend/'],
        capture_output=True,
        text=True
    )
    
    print("后端目录内容:")
    print(result.stdout)
    if result.stderr:
        print("错误:", result.stderr)
    
    # 检查是否存在主要文件
    files_to_check = [
        'app.py', 'main.py', 'config.py',
        'auth/utils.py', 'api/auth.py', 'routers/auth.py'
    ]
    
    print("\n检查关键文件:")
    for file_path in files_to_check:
        full_path = f"/home/elder_photo_project/backend/{file_path}"
        result = subprocess.run(
            ['ssh', 'root@36.112.162.239', f'ls -la {full_path}'],
            capture_output=True,
            text=True
        )
        if "No such file" in result.stderr:
            print(f"❌ {file_path}: 不存在")
        else:
            print(f"✅ {file_path}: 存在")

if __name__ == "__main__":
    check_server_structure()
