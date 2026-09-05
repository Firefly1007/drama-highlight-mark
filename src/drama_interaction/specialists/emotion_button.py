"""情绪按钮 Specialist。"""

from drama_interaction.specialists.base import BaseSpecialist


class EmotionButtonSpecialist(BaseSpecialist):
    """识别适合即时表达情绪的剧情节点。"""

    specialist_type = "emotion_button"
