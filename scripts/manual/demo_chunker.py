from app.services.chunker import split_text


text = """
Python装饰器是一种非常重要的Python编程机制。装饰器可以在不修改原函数代码的情况下增强函数的功能。它的核心思想是使用一个函数去包装另一个函数，从而在原函数执行之前或者执行之后增加额外的操作。装饰器通常接收一个函数作为参数，然后返回一个新的函数。在实际开发中，装饰器经常用于日志记录、权限验证、缓存、性能统计等场景。通过装饰器，我们可以把一些通用功能从具体业务函数中分离出来，从而减少重复代码，提高程序的可维护性和代码复用能力。使用装饰器还可以让程序结构更加清晰，使开发者能够更加方便地给多个函数添加相同的功能。
"""

chunks = split_text(
    text,
    chunk_size=200,
    chunk_overlap=50
)

print("Chunk数量：", len(chunks))

for i, chunk in enumerate(chunks):
    print("\n==============================")
    print("Chunk", i)
    print("长度：", len(chunk))
    print("内容：")
    print(chunk)