from app.services.embedding import embed_text
import numpy as np

text1 = "Python装饰器可以增强函数功能"
text2 = "装饰器能够在不修改原函数的情况下增加功能"
text3 = "今天天气非常不错"

vector1 = embed_text(text1)
vector2 = embed_text(text2)
vector3 = embed_text(text3)

similarity_12 = np.dot(vector1,vector2)
similarity_13 = np.dot(vector1,vector3)

print("12相似度：",similarity_12)
print("13相似度：",similarity_13)
