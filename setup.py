from setuptools import setup, find_packages

with open("requirements.txt", "r", encoding="utf-8") as f:
    requirements = [line.strip() for line in f if line.strip() and not line.startswith("#")]

setup(
    name="Web Archive",
    version="1.0.0",
    description="Advanced Wayback Machine subdomain extractor with filtering and multiple output formats",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="cumakurt",
    url="https://github.com/cumakurt/WebArchive",
    packages=find_packages(),
    install_requires=requirements,
    python_requires=">=3.10",
    entry_points={
        "console_scripts": [
            "webarchive.py=WebArchive:main",
        ],
    },
)
