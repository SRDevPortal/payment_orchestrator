from setuptools import setup, find_packages

setup(
    name='payment_orchestrator',
    version='0.0.1',
    description='Multi-gateway payment links, POS collections, webhooks, and ERPNext allocation for Frappe',
    author='OpenClaw',
    packages=find_packages(),
    include_package_data=True,
    zip_safe=False,
)
