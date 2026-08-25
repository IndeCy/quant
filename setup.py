"""
Setup script for the backtest package
"""

from setuptools import setup, find_packages

setup(
    name='quant-backtest',
    version='0.1.0',
    description='中国A股回测系统 (Chinese A-share Backtesting System)',
    author='IndeCy',
    packages=find_packages(),
    install_requires=[
        'pandas>=1.3.0',
        'numpy>=1.20.0',
        'matplotlib>=3.3.0',
        'scikit-learn>=1.4.0',
    ],
    python_requires='>=3.10',
)
