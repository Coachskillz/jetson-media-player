from setuptools import setup, find_packages

setup(
    name="jetson-media-player",
    version="0.1.0",
    description="Open-source media player for NVIDIA Jetson with AI triggers",
    author="Matt Skillman",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires=">=3.8",
    install_requires=[
        "PyYAML>=6.0",
        "pyzmq>=25.0",
        "requests>=2.31.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.4.0",
            "black>=23.0.0",
            "pylint>=2.17.0",
        ]
    },
)
