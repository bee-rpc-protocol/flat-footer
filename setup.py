from setuptools import setup, find_packages

setup(
    name='bee-rpc',
    version='0.0.4',

    url='https://github.com/bee-rpc/bee-rpc.git',

    py_modules=[
        'bee-rpc'
    ],
    install_requires=[
        'grpcio==1.56.0',
        'protobuf==4.23.3',
    ],
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    python_requires=">=3.11",
)
