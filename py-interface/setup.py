from setuptools import setup

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name='amdsmi',
    version='1.0.0+rocm-5.5.0',
    description="SMI LIB - AMD GPU Monitoring Library",
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=['amdsmi'],
    package_data={'': ['LICENSE']},
    include_package_data=True,
    python_requires=">=3.6",
)
