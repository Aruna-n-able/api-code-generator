# api-code-generator

A tool for generating REST API implementation files from WSDL definitions.

## Overview

This tool parses WSDL files sourced from the [n-central](https://github.com/nable-nc/n-central) repository and generates REST API implementation files—including Service, Controller, Transformer, and DTO classes—following the structure and standards defined in the [api-service](https://github.com/nable-nc/api-service) repository.

## Related Repositories

| Repository | URL | Role |
|---|---|---|
| **n-central** | https://github.com/nable-nc/n-central | Source of WSDL files that define available operations, request structures, and response structures |
| **api-service** | https://github.com/nable-nc/api-service | Reference implementation that defines the code structure, patterns, and standards used when generating REST API files |

## Features

- **WSDL Parsing**: Upload a WSDL file from the n-central repository to list all available operations with their request and response structures.
- **REST API Code Generation**: Generate Service, Controller, Transformer, and DTO classes that follow the conventions in the api-service repository.
- **Code Refinement**: Improve or refactor generated code through a chat interface.
- **Unit Test Generation**: Generate unit tests once the generated code is reviewed and accepted.
- **Robot Framework Test Generation**: Generate Robot Framework integration tests for the REST API.

## Workflow

1. Upload a WSDL file (from the n-central repository) to inspect available operations.
2. Click **Implement REST API** to generate implementation files based on the api-service repository structure.
3. Review and refine the generated code using the chat interface.
4. Generate unit tests when satisfied with the implementation.
5. Optionally generate Robot Framework tests.
