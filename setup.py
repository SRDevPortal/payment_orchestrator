from setuptools import setup, find_packages

setup(
    name='razorpay_integration',
    version='0.0.1',
    description='Unified payment orchestration for ERPNext/Frappe',
    author='OpenClaw',
    packages=find_packages(),
    include_package_data=True,
    zip_safe=False,
)
