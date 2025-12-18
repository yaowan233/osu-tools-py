from src.osu_lib.calculator import OsuCalculator

# 1. 实例化 (只需指定一次 DLL 路径)
# 如果你的 published_output 文件夹就在当前目录的 osu-tools 下，甚至不需要传参数
calc = OsuCalculator()

# 2. 调用计算
# 示例：Standard, HDDT, 98% Acc
result = calc.calculate(
    file_path="test5.osu",
    mode=0,
    mods=["DT", "HD", "HR"],
    acc=95.94,
    combo=331,
    statistics={'great': 457, 'miss': 9, 'ok': 23, 'meh': 0, 'slider_tail_hit': 244, 'large_tick_hit': 15}
)

if "error" in result:
    print("出错啦:", result["error"])
else:
    print(f"歌名: {result['stats_used']}")
    print(f"Stars: {result['stars']:.2f}")
    print(f"PP: {result['pp']:.2f}")
    print(f"max_combo: {result['max_combo']:.2f}")

