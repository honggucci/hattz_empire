"""
Math utilities - fibonacci and related functions.
"""

def fibonacci(n: int) -> int:
    """
    Calculate the nth Fibonacci number.

    Args:
        n: Index of Fibonacci sequence (0-indexed)

    Returns:
        nth Fibonacci number

    Raises:
        ValueError: If n is negative
    """
    if n < 0:
        raise ValueError("n must be non-negative")
    if n <= 1:
        return n

    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b


def fibonacci_sequence(n: int) -> list[int]:
    """
    Generate first n Fibonacci numbers.

    Args:
        n: Count of Fibonacci numbers to generate

    Returns:
        List of first n Fibonacci numbers
    """
    if n <= 0:
        return []
    if n == 1:
        return [0]

    result = [0, 1]
    for _ in range(2, n):
        result.append(result[-1] + result[-2])
    return result
