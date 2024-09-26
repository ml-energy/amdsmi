# AMDSMI Python Package

The AMDSMI Python Package provides an auto-generated Python wrapper for the `amdsmi` library, making it easy to interact with the library using Python. Every time a new tag is published to the `amdsmi` repository, the Python wrapper is automatically generated and published to PyPI, enabling seamless installation via:

```
pip install amdsmi
```

You can find the package on PyPI at: [AMDSMI on PyPI](https://pypi.org/project/amdsmi/).

For more detailed information about `amdsmi`, please refer to the `README.md` in the `py-interface` directory of the repository, or visit the official `amdsmi` repository: [ROCm/amdsmi](https://github.com/ROCm/amdsmi/).

## Versioning

The versioning of the AMDSMI Python package aligns with both `amdsmi` and ROCm versions to maintain consistency. The `amdsmi` version serves as the primary version, while the ROCm version is appended as a local version specifier. 

For example:
- When the tag `amdsmi_pkg_ver-24.6.0` is pushed, the package version will be `24.6.0`.
- When ROCm version `6.2.1` is integrated, the version becomes `24.6.3+rocm-6.2.1`.

This approach ensures clear tracking of updates across both `amdsmi` and ROCm components.
