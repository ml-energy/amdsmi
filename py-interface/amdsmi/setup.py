from setuptools import setup, find_packages
import os

setup(
    name="amdsmi",
    version="6.3.1",
    author="AMD",
    author_email="amd-smi.support@amd.com",
    description="AMDSMI Python LIB - AMD GPU Monitoring Library",
    url="https://github.com/ROCm/amdsmi",
    packages=find_packages(),
    install_requires=[
        "PyYAML>=3.0",
    ],
    classifiers=[
        "Programming Language :: Python :: 3",
    ],
    python_requires=">=3.6",
    include_package_data=True,
    package_data={
        '': ['*.so'],
    },
    zip_safe=False,
    license='amdsmi/LICENSE',
)
