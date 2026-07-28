# check_paths.py
import os

print("=" * 50)
print("1. deepseek_model 目录:")
if os.path.exists("deepseek_model"):
    for f in os.listdir("deepseek_model"):
        print(f"  {f}")
else:
    print("  ❌ 目录不存在")

print("\n" + "=" * 50)
print("2. output/checkpoint-27 目录:")
checkpoint_path = os.path.join("output", "checkpoint-27")
if os.path.exists(checkpoint_path):
    for f in os.listdir(checkpoint_path):
        size = os.path.getsize(os.path.join(checkpoint_path, f)) / 1024**2
        print(f"  {f} ({size:.2f} MB)")
else:
    print("  ❌ 目录不存在")

print("\n" + "=" * 50)
print("3. 查找所有 adapter 相关文件:")
for root, dirs, files in os.walk("output"):
    for f in files:
        if 'adapter' in f.lower():
            path = os.path.join(root, f)
            size = os.path.getsize(path) / 1024**2
            print(f"  {path} ({size:.2f} MB)")