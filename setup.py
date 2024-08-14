from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="entities_api",
    version="0.1.0",
    author="Francis N.",
    author_email="francis.neequaye@projectdavid.co.uk",
    description="A FastAPI-based API for managing AI entities",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/frankie336/entities_api",
    packages=find_packages(include=['entities', 'entities.*', 'entities_api', 'entities_api.*']),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
    ],
    python_requires=">=3.8",
    install_requires=[
        "anyio",
        "certifi",
        "h11",
        "httpcore",
        "httpx",
        "idna",
        "sniffio",
        "fastapi",
        "databases",
        "uvicorn",
        "sqlalchemy",
        "pydantic",
        "starlette",
        "asgiref",
        "click",
        "pymysql",
        "cryptography",
        "pytest",
        "typing_extensions",
        "python-dotenv",
        "alembic",
        "ollama",
        "typer",
        "flask",
        "flask-sqlalchemy",
        "spacy",
        "weasel",
    ],
    extras_require={
        "dev": [
            "pytest",
        ],
    },
    entry_points={
        "console_scripts": [
            "entities-api=entities_api.main:main",
        ],
    },
)