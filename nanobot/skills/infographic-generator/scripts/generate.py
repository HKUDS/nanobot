#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
高密度信息大图生成器

用法:
    python3 generate.py "主题名称" --style blueprint
    python3 generate.py "AI Agent 提示词工程" --style morandi --output prompt.txt
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class InfographicGenerator:
    """高密度信息大图生成器"""
    
    # 视觉风格配置
    STYLES = {
        "blueprint": {
            "name": "坐标蓝图·波普实验室",
            "colors": {
                "background": "#F2F2F2",
                "system_base": "#B8D8BE", 
                "alert_accent": "#E91E63",
                "highlight": "#FFF200",
                "line_art": "#2D2926"
            },
            "reference": "《字体结构拆解》精密感 + 《HBL 30周年》色彩冲击力"
        },
        "morandi": {
            "name": "莫兰迪色系",
            "colors": {
                "background": "#F5F3F0",
                "system_base": "#B5B5A8",
                "alert_accent": "#D4A5A5", 
                "highlight": "#E8D5C4",
                "line_art": "#6B6B6B"
            },
            "reference": "柔和高级感，适合生活方式内容"
        },
        "vintage": {
            "name": "复古风",
            "colors": {
                "background": "#F4ECD8",
                "system_base": "#C9B99A",
                "alert_accent": "#8B4513",
                "highlight": "#DAA520", 
                "line_art": "#2F2F2F"
            },
            "reference": "怀旧质感，适合历史文化内容"
        },
        "minimal": {
            "name": "极简黑白",
            "colors": {
                "background": "#FFFFFF",
                "system_base": "#E0E0E0",
                "alert_accent": "#000000",
                "highlight": "#666666",
                "line_art": "#333333"
            },
            "reference": "信息密集，适合数据报告"
        }
    }
    
    # 6-7个标准模块
    DEFAULT_MODULES = [
        {"coord": "A-01", "type": "品牌阵列/对比区", "name": "核心对比"},
        {"coord": "B-05", "type": "核心参数/刻度区", "name": "关键参数"},
        {"coord": "C-12", "type": "结构拆解/细节图", "name": "结构拆解"},
        {"coord": "D-03", "type": "流程/时间轴区", "name": "流程步骤"},
        {"coord": "E-08", "type": "案例/应用场景区", "name": "实战案例"},
        {"coord": "F-11", "type": "总结/行动指南区", "name": "行动指南"}
    ]
    
    def __init__(self, style="blueprint"):
        """初始化生成器
        
        Args:
            style: 视觉风格 (blueprint/morandi/vintage/minimal)
        """
        self.style = style
        self.style_config = self.STYLES.get(style, self.STYLES["blueprint"])
        
    def generate(self, topic, modules=None):
        """生成完整的信息图 prompt
        
        Args:
            topic: 主题名称
            modules: 自定义模块列表（可选）
            
        Returns:
            dict: 包含完整prompt和元数据的字典
        """
        if modules is None:
            modules = self.DEFAULT_MODULES
            
        # 构建视觉坐标系统
        coordinate_system = self._build_coordinate_system(topic, modules)
        
        # 构建生图prompt
        image_prompt = self._build_image_prompt(topic, coordinate_system)
        
        return {
            "topic": topic,
            "style": self.style,
            "style_name": self.style_config["name"],
            "coordinate_system": coordinate_system,
            "image_prompt": image_prompt,
            "created_at": datetime.now().isoformat()
        }
    
    def _build_coordinate_system(self, topic, modules):
        """构建视觉坐标系统"""
        lines = [f"图片1 → 核心主题：{topic}"]
        
        for module in modules:
            coord = module["coord"]
            name = module["name"]
            type_desc = module["type"]
            lines.append(f"├─ 坐标 {coord}：{name}（{type_desc}）")
        
        lines.append("└─ 右下角小字：模板by WaytoAGI")
        
        return "\n".join(lines)
    
    def _build_image_prompt(self, topic, coordinate_system):
        """构建生图prompt"""
        colors = self.style_config["colors"]
        
        prompt = f"""Create a high-density, professional information design infographic for Xiaohongshu about「{topic}」.

=== CRITICAL STYLE REQUIREMENTS (SYSTEMIC & EXPERIMENTAL) ===

【COLOR PALETTE - {self.style_config["name"].upper()}】
- BACKGROUND: {colors['background']}
- SYSTEMIC BASE: {colors['system_base']} for major functional blocks
- HIGH-ALERT ACCENT: {colors['alert_accent']} for critical warnings
- MARKER HIGHLIGHTS: {colors['highlight']} for keywords
- LINE ART: {colors['line_art']} for technical grids

【TYPOGRAPHY - DATA VISUALIZATION】
- TITLES: Bold, condensed sans-serif (Oswald/Bebas Neue style)
- BODY: Clean, technical sans-serif (Roboto/Inter style)
- DATA: Monospaced for numbers (JetBrains Mono)

【COMPOSITION - VISUAL COORDINATES】
- Strict Grid System: 12-column blueprint-grid logic
- Module Isolation: Each coordinate module visually distinct
- Connecting Lines: Thin, dashed technical lines
- Whitespace: Engineered negative space with blueprint lines

【CONTENT LAYOUT - HIGH DENSITY】
- No Paragraphs: All text in bullet points, diagrams, or short labels
- Data Hierarchy: Font size/weight shows importance
- Corner Details: "FIG.1-A", "SCALE 1:50", "CONFIDENTIAL"

【FINAL OUTPUT REQUIREMENTS】
- Aspect Ratio: 2:3 (Portrait)
- Resolution: Minimum 2K (2048px width)
- Style: "Infographic," "Technical Illustration," "Blueprint," "Pop Art"
- Mood: "Precise," "Analytical," "Bold," "Experimental"

CONTENT TO VISUALIZE:
{coordinate_system}
"""
        return prompt
    
    def save(self, result, output_path=None):
        """保存结果到文件
        
        Args:
            result: generate() 返回的结果字典
            output_path: 输出文件路径（可选）
        """
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_topic = "".join(c if c.isalnum() else "_" for c in result["topic"])
            output_path = f"{safe_topic}_{timestamp}.txt"
        
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("# 高密度信息大图生成结果\n")
            f.write(f"# 主题: {result['topic']}\n")
            f.write(f"# 风格: {result['style_name']}\n")
            f.write(f"# 生成时间: {result['created_at']}\n")
            f.write("=" * 60 + "\n\n")
            
            f.write("## 视觉坐标系统\n\n")
            f.write(result["coordinate_system"] + "\n\n")
            
            f.write("## 生图 Prompt\n\n")
            f.write("```\n")
            f.write(result["image_prompt"])
            f.write("\n```\n")
        
        return output_path


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(description="高密度信息大图生成器")
    parser.add_argument("topic", help="主题名称")
    parser.add_argument("--style", default="blueprint", 
                       choices=["blueprint", "morandi", "vintage", "minimal"],
                       help="视觉风格 (默认: blueprint)")
    parser.add_argument("--output", "-o", help="输出文件路径")
    parser.add_argument("--json", action="store_true", help="输出JSON格式")
    
    args = parser.parse_args()
    
    # 生成
    generator = InfographicGenerator(style=args.style)
    result = generator.generate(args.topic)
    
    # 输出
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        output_path = generator.save(result, args.output)
        print(f"✅ 已生成: {output_path}")
        print(f"\n主题: {result['topic']}")
        print(f"风格: {result['style_name']}")
        print(f"\n视觉坐标系统:\n{result['coordinate_system']}")


if __name__ == "__main__":
    main()
