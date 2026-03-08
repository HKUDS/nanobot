#!/usr/bin/env python3
"""
吴娜口播批量生成示例

一键生成多段口播音频
"""

import sys
import os

# 添加到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from voice_clone import generate_speech, poll_result, download_audio

# 配置
VOICE_ID = "wuna-001"  # 已克隆的吴娜声音
OUTPUT_DIR = "/tmp/wuna_koubo"

# 口播文本列表
KOUBO_TEXTS = [
    # 开场
    "我是外企面试官。2026年求职，你一定要学会用人工智能！不懂人工智能的简历直接被淘汰，会用的轻松拿下高薪offer！",
    
    # 第一板块
    "很多人写简历写3天，最后石沉大海。不会用STAR法则，经历描述就像流水账。正确做法是：把你的经历喂给AI，让它帮你提炼关键词。提示词这样写——请用STAR法则优化这段经历，突出数据分析能力。3分钟就能生成3个版本，针对不同岗位定向投递。简历通过率直接从5%提升到30%！",
    
    # 第二板块
    "面试紧张，自我介绍都说不顺？不知道面试官会问什么？这样做：把岗位描述发给AI，说请根据这个岗位，预测10个面试问题。然后让AI扮演面试官，跟你进行语音模拟。录下你的回答，AI还能帮你分析哪里逻辑不清晰。面试成功率直接提升2倍！",
    
    # 第三板块
    "只会用BOSS直聘，和千万人抢同一个岗位？不知道哪些公司在悄悄扩张、高薪抢人？让AI帮你分析：2026年哪些行业的AI人才需求增长最快？用AI监控目标公司的招聘动态、融资新闻，提前发现那些小而美的外企和独角兽公司。找到别人看不到的机会！",
    
    # 结尾
    "记住，2026年不是AI抢了你的饭碗，是不会用AI的人，被会用的抢了饭碗！另外我还整理了一份AI求职工具包，包含30个写简历、模拟面试、职业调研的提示词模板。需要的评论区扣AI，我发给你！关注我，帮你轻松拿offer！"
]


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    print("=" * 60)
    print("吴娜口播批量生成")
    print("=" * 60)
    print(f"Voice ID: {VOICE_ID}")
    print(f"输出目录: {OUTPUT_DIR}")
    print(f"共 {len(KOUBO_TEXTS)} 段口播")
    print("=" * 60)
    
    for i, text in enumerate(KOUBO_TEXTS, 1):
        print(f"\n🎵 [{i}/{len(KOUBO_TEXTS)}] 生成中...")
        print(f"   {text[:60]}...")
        
        try:
            # 提交任务
            request_id, _ = generate_speech(text, VOICE_ID)
            
            # 等待结果
            audio_url = poll_result(request_id, timeout=120)
            
            # 下载
            output_path = os.path.join(OUTPUT_DIR, f"wuna_koubo_{i:02d}.mp3")
            download_audio(audio_url, output_path)
            
            print(f"   ✅ 已保存: {output_path}")
        
        except Exception as e:
            print(f"   ❌ 失败: {e}")
            continue
    
    print("\n" + "=" * 60)
    print(f"🎉 全部完成！共生成 {len(KOUBO_TEXTS)} 个音频文件")
    print(f"📁 输出目录: {OUTPUT_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()
