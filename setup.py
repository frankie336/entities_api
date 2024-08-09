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
       packages=find_packages(include=['entities_api', 'entities_api.*', 'entities', 'entities.*']),
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
           "anyio==3.6.2",
           "certifi==2024.2.2",
           "h11==0.14.0",
           "httpcore==1.0.4",
           "httpx==0.27.0",
           "idna==3.6",
           "sniffio==1.3.1",
           "fastapi~=0.111.1",
           "databases==0.5.5",
           "uvicorn~=0.22.0",
           "sqlalchemy>=2.0.16",  # Updated to be compatible with Flask-SQLAlchemy
           "pydantic~=2.5.3",
           "starlette~=0.37.2",
           "asgiref==3.4.1",
           "click>=8.1.3",  # Updated to be compatible with Flask
           "pymysql==1.0.2",
           "cryptography~=42.0.0",
           "pytest~=7.4.3",
           "typing_extensions~=4.11.0",
           "python-dotenv~=1.0.1",
           "alembic~=1.11.0",
           "ollama==0.3.1",  # Specify the version
           "typer<0.10.0,>=0.3.0",  # Specify a version range compatible with Spacy and Weasel
           "flask>=3.0.3",  # Add Flask with a minimum version
           "flask-sqlalchemy>=3.1.1",  # Add Flask-SQLAlchemy with a minimum version
       ],
       extras_require={
           "dev": [
               "pytest~=7.4.3",
           ],
       },
       entry_points={
           "console_scripts": [
               "entities-api=entities_api.main:main",
           ],
       },
   )