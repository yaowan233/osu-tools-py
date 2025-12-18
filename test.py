from src.osu_lib.calculator import OsuCalculator

# 1. 实例化 (只需指定一次 DLL 路径)
# 如果你的 published_output 文件夹就在当前目录的 osu-tools 下，甚至不需要传参数
calc = OsuCalculator()

# 2. 调用计算
# 示例：Standard, HDDT, 98% Acc
result = calc.calculate(
    file_path="test4.osu",
    mode=0,
    mods=["CL"],
    acc=94.13,
    combo=295,
    statistics={'great': 299, 'miss': 1, 'ok': 26, 'meh': 1}
)

if "error" in result:
    print("出错啦:", result["error"])
else:
    print(f"歌名: {result['stats_used']}")
    print(f"Stars: {result['stars']:.2f}")
    print(f"PP: {result['pp']:.2f}")
