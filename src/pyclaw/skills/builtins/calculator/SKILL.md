---
name: calculator
description: Perform mathematical calculations. Use when the user asks for math, arithmetic, unit conversions, or numerical computations.
---

# Calculator Skill

Perform mathematical calculations accurately.

## Usage

When the user asks for calculations, use Python expressions via the exec tool.

### Steps

1. Parse the mathematical expression from the user's request.
2. Write a Python expression or short script to compute the result.
3. Execute it using the exec tool.
4. Present the result clearly, including units if applicable.

### Tips

- Use Python's `math` module for advanced functions (sin, cos, log, etc.).
- Use `decimal.Decimal` for financial calculations requiring precision.
- For unit conversions, compute the conversion factor explicitly.
