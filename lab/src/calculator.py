"""实验用示例代码：故意留了几个小问题供 Agent 发现。"""

def add(a, b):
    return a + b


def divide(a, b):
    # 除零未处理
    return a / b


def average(values):
    # 空列表会除零
    return sum(values) / len(values)
