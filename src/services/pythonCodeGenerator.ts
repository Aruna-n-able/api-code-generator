/**
 * Python / FastAPI code generator.
 *
 * Produces the same six conceptual files as the Java generator, but in Python:
 *   requestDto      → Pydantic request schema   ({Op}Request)
 *   responseDto     → Pydantic response schema  ({Op}Response)
 *   serviceInterface → Abstract base class / Protocol ({Op}ServiceBase)
 *   serviceImpl     → Concrete service           ({Op}Service)
 *   transformer     → Transformer class          ({Op}Transformer)
 *   controller      → FastAPI APIRouter          ({op}_router.py)
 *
 * XSD primitive types are already mapped to Java types by the WSDL parser.
 * We re-map them here to Python / Pydantic types.
 */

import type { WsdlOperation, WsdlField, GeneratedFiles } from '../types';

// ── type mapping ──────────────────────────────────────────────────────────────

/** Map a Java type (as produced by the WSDL parser) → Python / Pydantic type */
function javaToPython(javaType: string): string {
  // Handle List<X> → list[X]
  if (javaType.startsWith('List<') && javaType.endsWith('>')) {
    const inner = javaType.slice(5, -1);
    return `list[${javaToPython(inner)}]`;
  }
  const MAP: Record<string, string> = {
    String: 'str',
    Integer: 'int',
    Long: 'int',
    Short: 'int',
    Byte: 'int',
    Double: 'float',
    Float: 'float',
    BigDecimal: 'Decimal',
    Boolean: 'bool',
    LocalDateTime: 'datetime',
    LocalDate: 'date',
    LocalTime: 'time',
    'byte[]': 'bytes',
    Object: 'Any',
  };
  return MAP[javaType] ?? 'str';
}

/** Collect the set of imports needed for a list of fields */
function pythonImports(fields: WsdlField[]): string[] {
  const imports = new Set<string>();
  const check = (t: string) => {
    const py = javaToPython(t);
    if (py === 'Decimal') imports.add('from decimal import Decimal');
    if (py === 'datetime') imports.add('from datetime import datetime');
    if (py === 'date') imports.add('from datetime import date');
    if (py === 'time') imports.add('from datetime import time');
    if (py === 'Any') imports.add('from typing import Any');
    if (py.startsWith('list[')) {
      // recurse for inner type
      const inner = py.slice(5, -1);
      if (inner === 'datetime') imports.add('from datetime import datetime');
      if (inner === 'date') imports.add('from datetime import date');
      if (inner === 'Decimal') imports.add('from decimal import Decimal');
    }
  };
  for (const f of fields) check(f.type);
  return [...imports].sort();
}

// ── helpers ───────────────────────────────────────────────────────────────────

function toSnake(name: string): string {
  return name
    .replace(/([A-Z])/g, (_, c, i) => (i > 0 ? '_' : '') + c.toLowerCase())
    .replace(/^_/, '');
}

function toPascal(name: string): string {
  return name.charAt(0).toUpperCase() + name.slice(1);
}

function httpMethod(opName: string): 'GET' | 'POST' | 'PUT' | 'DELETE' {
  const lower = opName.toLowerCase();
  if (lower.startsWith('get') || lower.startsWith('list') || lower.startsWith('find') || lower.startsWith('fetch') || lower.startsWith('query') || lower.startsWith('search')) return 'GET';
  if (lower.startsWith('delete') || lower.startsWith('remove')) return 'DELETE';
  if (lower.startsWith('update') || lower.startsWith('modify') || lower.startsWith('change') || lower.startsWith('set')) return 'PUT';
  return 'POST';
}

function toKebab(name: string): string {
  return name
    .replace(/([A-Z])/g, (_, c, i) => (i > 0 ? '-' : '') + c.toLowerCase())
    .replace(/^-/, '');
}

/** Render Pydantic model fields */
function renderPydanticFields(fields: WsdlField[]): string {
  if (!fields.length) return '    placeholder: str = ""  # No fields extracted — add fields as needed';
  return fields
    .map((f) => {
      const pyType = javaToPython(f.type);
      const optional = !f.required;
      const typeStr = optional ? `Optional[${pyType}]` : pyType;
      const default_ = optional ? ' = None' : '';
      return `    ${toSnake(f.name)}: ${typeStr}${default_}`;
    })
    .join('\n');
}

function needsOptional(fields: WsdlField[]): boolean {
  return fields.some((f) => !f.required);
}

/** Sample value for a Python type (for test generation) */
function samplePyValue(javaType: string, fieldName: string): string {
  const py = javaToPython(javaType);
  if (py === 'str') return `"test_${toSnake(fieldName)}"`;
  if (py === 'int') return '1';
  if (py === 'float') return '1.0';
  if (py === 'bool') return 'True';
  if (py === 'Decimal') return 'Decimal("1.0")';
  if (py === 'datetime') return 'datetime.now()';
  if (py === 'date') return 'date.today()';
  if (py.startsWith('list[')) return '[]';
  return 'None';
}

// ── generators ────────────────────────────────────────────────────────────────

export function pyRequestDto(op: WsdlOperation): string {
  const className = `${toPascal(op.name)}Request`;
  const extraImports = pythonImports(op.inputFields);
  const hasOptional = needsOptional(op.inputFields);

  return `"""Pydantic request schema for the '${op.name}' N-Central WSDL operation."""
from __future__ import annotations

${hasOptional ? 'from typing import Optional\n' : ''}from pydantic import BaseModel, Field${extraImports.length ? '\n' + extraImports.join('\n') : ''}


class ${className}(BaseModel):
    """Request body for the ${op.name} endpoint."""

${renderPydanticFields(op.inputFields)}

    class Config:
        populate_by_name = True
        json_schema_extra = {
            "example": {
${op.inputFields
  .map((f) => `                "${toSnake(f.name)}": ${samplePyValue(f.type, f.name)}`)
  .join(',\n') || '                "placeholder": ""'}
            }
        }
`;
}

export function pyResponseDto(op: WsdlOperation): string {
  const className = `${toPascal(op.name)}Response`;
  const extraImports = pythonImports(op.outputFields);
  const hasOptional = needsOptional(op.outputFields);

  return `"""Pydantic response schema for the '${op.name}' N-Central WSDL operation."""
from __future__ import annotations

${hasOptional ? 'from typing import Optional\n' : ''}from pydantic import BaseModel${extraImports.length ? '\n' + extraImports.join('\n') : ''}


class ${className}(BaseModel):
    """Response body for the ${op.name} endpoint."""

${renderPydanticFields(op.outputFields)}

    class Config:
        populate_by_name = True
`;
}

export function pyServiceInterface(op: WsdlOperation): string {
  const pascal = toPascal(op.name);
  const method = httpMethod(op.name);
  const isGetter = method === 'GET';

  return `"""Abstract service base class for the '${op.name}' N-Central WSDL operation."""
from __future__ import annotations

from abc import ABC, abstractmethod

from .schemas import ${pascal}Request, ${pascal}Response


class ${pascal}ServiceBase(ABC):
    """
    Abstract base class for the ${op.name} service.

    Implementations must delegate to the N-Central SOAP client and convert
    results into REST-friendly response objects via the transformer.
    """

    @abstractmethod
    def ${toSnake(op.name)}(${isGetter ? 'self' : `self, request: ${pascal}Request`}) -> ${pascal}Response:
        """
        ${isGetter ? 'Retrieve' : 'Execute'} the ${op.name} operation.

        ${isGetter ? '' : `Args:
            request: The validated REST request DTO.

        `}Returns:
            A ${pascal}Response containing the N-Central SOAP result.
        """
        ...
`;
}

export function pyServiceImpl(op: WsdlOperation): string {
  const pascal = toPascal(op.name);
  const snake = toSnake(op.name);
  const method = httpMethod(op.name);
  const isGetter = method === 'GET';

  return `"""Concrete service implementation for the '${op.name}' N-Central WSDL operation."""
from __future__ import annotations

import logging

from .schemas import ${pascal}Request, ${pascal}Response
from .service_base import ${pascal}ServiceBase
from .transformer import ${pascal}Transformer
from ..soap.client import NCentralSoapClient

logger = logging.getLogger(__name__)


class ${pascal}Service(${pascal}ServiceBase):
    """
    Implements :class:\`${pascal}ServiceBase\`.

    Delegates to :class:\`NCentralSoapClient\` and uses
    :class:\`${pascal}Transformer\` to convert between REST and SOAP types.
    """

    def __init__(
        self,
        soap_client: NCentralSoapClient,
        transformer: ${pascal}Transformer,
    ) -> None:
        self._soap_client = soap_client
        self._transformer = transformer

    def ${snake}(${isGetter ? 'self' : `self, request: ${pascal}Request`}) -> ${pascal}Response:
        logger.info("Executing ${op.name}${isGetter ? '' : ' with request: %s'}"${isGetter ? '' : ', request'})

        ${isGetter ? '' : `soap_request = self._transformer.to_soap_request(request)\n        `}soap_response = self._soap_client.${snake}(${isGetter ? '' : 'soap_request'})

        response = self._transformer.to_response(soap_response)
        logger.debug("${op.name} response: %s", response)
        return response
`;
}

export function pyTransformer(op: WsdlOperation): string {
  const pascal = toPascal(op.name);
  const method = httpMethod(op.name);
  const isGetter = method === 'GET';

  const inputMappings = op.inputFields.length
    ? op.inputFields
        .map((f) => `            ${toSnake(f.name)}=request.${toSnake(f.name)},`)
        .join('\n')
    : '            # map fields from request';

  const outputMappings = op.outputFields.length
    ? op.outputFields
        .map((f) => `            ${toSnake(f.name)}=soap_response.${toSnake(f.name)},`)
        .join('\n')
    : '            # map fields from soap_response';

  return `"""Transformer for the '${op.name}' N-Central WSDL operation."""
from __future__ import annotations

from .schemas import ${pascal}Request, ${pascal}Response
from ..soap.models import ${pascal}SoapRequest, ${pascal}SoapResponse


class ${pascal}Transformer:
    """
    Converts between REST DTOs and N-Central SOAP types for the
    ${op.name} operation.
    """
${
  isGetter
    ? ''
    : `
    def to_soap_request(self, request: ${pascal}Request) -> ${pascal}SoapRequest:
        """Convert a REST request DTO → SOAP request object."""
        return ${pascal}SoapRequest(
${inputMappings}
        )
`
}
    def to_response(self, soap_response: ${pascal}SoapResponse) -> ${pascal}Response:
        """Convert a SOAP response → REST response DTO."""
        return ${pascal}Response(
${outputMappings}
        )
`;
}

export function pyController(op: WsdlOperation): string {
  const pascal = toPascal(op.name);
  const snake = toSnake(op.name);
  const method = httpMethod(op.name);
  const endpoint = `/${toKebab(op.name)}`;
  const isGetter = method === 'GET';
  const httpDecorator = method.toLowerCase();

  const statusCode = method === 'POST' ? ', status_code=201' : '';
  const requestParam = isGetter ? '' : `, request: ${pascal}Request`;
  const serviceCall = isGetter ? `${snake}()` : `${snake}(request)`;

  return `"""FastAPI router for the '${op.name}' N-Central WSDL operation."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends${method === 'DELETE' ? ', Response' : ''}

from .schemas import ${pascal}Request, ${pascal}Response
from .service import ${pascal}Service
from ..dependencies import get_${snake}_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["${pascal}"])


@router.${httpDecorator}(
    "${endpoint}",
    response_model=${method === 'DELETE' ? 'None' : `${pascal}Response`},
    summary="${op.name}",
    description="${op.documentation ?? `REST endpoint wrapping the N-Central ${op.name} WSDL operation.`}"${statusCode},
)
${method === 'DELETE' ? `async def ${snake}(
    service: ${pascal}Service = Depends(get_${snake}_service),
) -> None:
    logger.info("Received ${op.name} request")
    service.${serviceCall}` : `async def ${snake}(${requestParam ? `\n    ${isGetter ? '' : `request: ${pascal}Request,\n    `}` : ''}service: ${pascal}Service = Depends(get_${snake}_service),
) -> ${pascal}Response:
    logger.info("Received ${op.name} request${isGetter ? '' : ': %s'}"${isGetter ? '' : ', request'})
    return service.${serviceCall}`}
`;
}

export function pyApiClient(op: WsdlOperation): string {
  const pascal = toPascal(op.name);
  const snake = toSnake(op.name);
  const method = httpMethod(op.name);
  const isGetter = method === 'GET';
  const endpoint = `/api/v1/${toKebab(op.name)}`;
  const hasBody = !isGetter && method !== 'DELETE';

  const schemaImport = hasBody
    ? `from .schemas import ${pascal}Request, ${pascal}Response`
    : `from .schemas import ${pascal}Response`;

  const param = isGetter || method === 'DELETE' ? 'self' : `self, request: ${pascal}Request`;
  const returnType = method === 'DELETE' ? 'None' : `${pascal}Response`;
  const usageCall = isGetter ? `result = client.${snake}()` : `result = client.${snake}(request)`;

  let httpCall: string;
  if (method === 'GET') {
    httpCall = `        response = self._client.get(f"{self.base_url}${endpoint}")\n        response.raise_for_status()\n        return ${pascal}Response(**response.json())`;
  } else if (method === 'DELETE') {
    httpCall = `        response = self._client.delete(f"{self.base_url}${endpoint}")\n        response.raise_for_status()`;
  } else if (method === 'POST') {
    httpCall = `        response = self._client.post(\n            f"{self.base_url}${endpoint}",\n            content=request.model_dump_json(),\n            headers={"Content-Type": "application/json"},\n        )\n        response.raise_for_status()\n        return ${pascal}Response(**response.json())`;
  } else {
    httpCall = `        response = self._client.put(\n            f"{self.base_url}${endpoint}",\n            content=request.model_dump_json(),\n            headers={"Content-Type": "application/json"},\n        )\n        response.raise_for_status()\n        return ${pascal}Response(**response.json())`;
  }

  return `"""REST API client for the '${op.name}' endpoint."""
from __future__ import annotations

import httpx

${schemaImport}


class ${pascal}ApiClient:
    """
    Typed HTTP client for the ${op.name} REST endpoint.

    Use this class to call the generated REST API from another
    Python service or script.

    Example::

        with ${pascal}ApiClient(base_url="http://localhost:8000") as client:
            ${usageCall}
    """

    def __init__(self, base_url: str = "http://localhost:8000", timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout)

    def ${snake}(${param}) -> ${returnType}:
        """
        Call the ${op.name} REST endpoint.

        Raises:
            httpx.HTTPStatusError: When the server returns a non-2xx status.
        """
${httpCall}

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._client.close()

    def __enter__(self) -> "${pascal}ApiClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
`;
}

export function generateJsClientTs(op: WsdlOperation): string {
  const camel = toCamel(op.name);
  const pascal = toPascal(op.name);
  const method = httpMethod(op.name);
  const isGetter = method === 'GET';
  const endpoint = `/api/v1/${toKebab(op.name)}`;
  const hasBody = !isGetter && method !== 'DELETE';

  const fetchCall = hasBody
    ? `  const response = await fetch(\`\${baseUrl}${endpoint}\`, {\n    method: '${method}',\n    headers: { 'Content-Type': 'application/json', ...headers },\n    body: JSON.stringify(request),\n  });`
    : `  const response = await fetch(\`\${baseUrl}${endpoint}\`, {\n    method: '${method}',\n    headers: { 'Content-Type': 'application/json', ...headers },\n  });`;

  const funcParams = hasBody
    ? `request, { baseUrl = 'http://localhost:8080', headers = {} } = {}`
    : `{ baseUrl = 'http://localhost:8080', headers = {} } = {}`;

  const jsdocParam = hasBody ? ` * @param {object} request  The request body matching the ${pascal}Request schema.\n` : '';
  const returnTypeDoc = method === 'DELETE'
    ? ' * @returns {Promise<void>}'
    : ` * @returns {Promise<object>} The ${pascal}Response JSON object.`;

  const resolveBlock = method === 'DELETE' ? '  // DELETE returns no body' : '  return response.json();';

  return `/**
 * JavaScript REST API client for the ${op.name} endpoint.
 *
 * Generated from the N-Central WSDL operation '${op.name}'.
 * Drop this file into any JS/TS project — no dependencies required.
 *
 * @example
 * import { ${camel} } from './${toKebab(op.name)}_client.js';
 *
 * // Usage:
 * const result = await ${camel}(${hasBody ? 'request, ' : ''}{ baseUrl: 'https://your-api-host' });
 * console.log(result);
 */

'use strict';

/**
 * Call the ${op.name} REST endpoint.
 *
${jsdocParam} * @param {string} [options.baseUrl]   Base URL of the REST server (default: 'http://localhost:8080').
 * @param {object} [options.headers]   Extra HTTP headers to include.
 ${returnTypeDoc}
 * @throws {Error} When the server returns a non-OK HTTP status.
 */
export async function ${camel}(${funcParams}) {
${fetchCall}

  if (!response.ok) {
    const errorText = await response.text().catch(() => response.statusText);
    throw new Error(\`${op.name} failed: \${response.status} \${errorText}\`);
  }

  ${resolveBlock}
}
`;
}

export function pyGenerateAllFiles(op: WsdlOperation): GeneratedFiles {
  return {
    requestDto: pyRequestDto(op),
    responseDto: pyResponseDto(op),
    serviceInterface: pyServiceInterface(op),
    serviceImpl: pyServiceImpl(op),
    transformer: pyTransformer(op),
    controller: pyController(op),
    apiClient: pyApiClient(op),
    jsClient: generateJsClientTs(op),
  };
}

// ── test generators ───────────────────────────────────────────────────────────

export function pyUnitTests(op: WsdlOperation): string {
  const pascal = toPascal(op.name);
  const snake = toSnake(op.name);
  const method = httpMethod(op.name);
  const isGetter = method === 'GET';
  const endpoint = `/api/v1/${toKebab(op.name)}`;

  const inputSample = op.inputFields.length
    ? op.inputFields
        .map((f) => `        ${toSnake(f.name)}=${samplePyValue(f.type, f.name)},`)
        .join('\n')
    : '        # no input fields';

  const outputSample = op.outputFields.length
    ? op.outputFields
        .map((f) => `        ${toSnake(f.name)}=${samplePyValue(f.type, f.name)},`)
        .join('\n')
    : '        # no output fields';

  return `"""Unit tests for ${pascal}Service (pytest + unittest.mock)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ..schemas import ${pascal}Request, ${pascal}Response
from ..service import ${pascal}Service
from ..transformer import ${pascal}Transformer
from ...soap.client import NCentralSoapClient
from ...soap.models import ${pascal}SoapRequest, ${pascal}SoapResponse


@pytest.fixture()
def soap_client() -> MagicMock:
    return MagicMock(spec=NCentralSoapClient)


@pytest.fixture()
def transformer() -> MagicMock:
    return MagicMock(spec=${pascal}Transformer)


@pytest.fixture()
def service(soap_client: MagicMock, transformer: MagicMock) -> ${pascal}Service:
    return ${pascal}Service(soap_client=soap_client, transformer=transformer)


class TestService${pascal}:
    def test_${snake}_returns_expected_response(
        self,
        service: ${pascal}Service,
        soap_client: MagicMock,
        transformer: MagicMock,
    ) -> None:
        """Happy path: successful execution returns the expected response."""
        # Arrange
        ${isGetter ? '' : `request = ${pascal}Request(
${inputSample}
        )
        `}expected_response = ${pascal}Response(
${outputSample}
        )
        soap_response = ${pascal}SoapResponse()
        ${isGetter ? '' : `transformer.to_soap_request.return_value = ${pascal}SoapRequest()\n        `}soap_client.${snake}.return_value = soap_response
        transformer.to_response.return_value = expected_response

        # Act
        result = service.${snake}(${isGetter ? '' : 'request'})

        # Assert
        assert result == expected_response
        ${isGetter ? '' : `transformer.to_soap_request.assert_called_once_with(request)\n        `}soap_client.${snake}.assert_called_once()
        transformer.to_response.assert_called_once_with(soap_response)

    def test_${snake}_propagates_soap_exception(
        self,
        service: ${pascal}Service,
        soap_client: MagicMock,
        transformer: MagicMock,
    ) -> None:
        """SOAP client errors must propagate to the caller."""
        ${isGetter ? '' : `transformer.to_soap_request.return_value = ${pascal}SoapRequest()\n        `}soap_client.${snake}.side_effect = RuntimeError("SOAP fault")

        with pytest.raises(RuntimeError, match="SOAP fault"):
            service.${snake}(${isGetter ? '' : `${pascal}Request()`})


# ─── FastAPI endpoint tests ───────────────────────────────────────────────────
# Place in a separate test_${snake}_router.py and uncomment:

# from fastapi.testclient import TestClient
# from unittest.mock import MagicMock
# from ..router import router
# from ..service import ${pascal}Service
# from ..dependencies import get_${snake}_service
# from ...main import app
#
# def test_${snake}_endpoint_returns_${method === 'POST' ? '201' : '200'}():
#     mock_svc = MagicMock(spec=${pascal}Service)
#     mock_svc.${snake}.return_value = ${pascal}Response(${op.outputFields
    .slice(0, 2)
    .map((f) => `${toSnake(f.name)}=${samplePyValue(f.type, f.name)}`)
    .join(', ')})
#     app.dependency_overrides[get_${snake}_service] = lambda: mock_svc
#     client = TestClient(app)
#     resp = client.${method.toLowerCase()}("${endpoint}"${isGetter ? '' : `, json={}`})
#     assert resp.status_code == ${method === 'POST' ? '201' : '200'}
#     app.dependency_overrides.clear()
`;
}

export function pyRobotTests(op: WsdlOperation): string {
  // Robot Framework tests are the same regardless of backend language
  const pascal = toPascal(op.name);
  const snake = toSnake(op.name);
  const method = httpMethod(op.name);
  const endpoint = `/api/v1/${toKebab(op.name)}`;
  const isGetter = method === 'GET';

  const requestDict = op.inputFields.length
    ? op.inputFields
        .map((f) => `    ...    ${toSnake(f.name)}=<value>`)
        .join('\n')
    : '    ...    # no request body';

  const responseAssertions = op.outputFields.length
    ? op.outputFields
        .slice(0, 3)
        .map(
          (f) => `    Should Not Be Empty    \${response.json()['${toSnake(f.name)}']}`,
        )
        .join('\n')
    : '    Should Not Be Empty    \${response.json()}';

  return `*** Settings ***
Library     Collections
Library     RequestsLibrary
Library     String

Suite Setup    Create Session    ncentral_api    \${BASE_URL}    verify=false

*** Variables ***
\${BASE_URL}         http://localhost:8000
\${CONTENT_TYPE}     application/json

*** Test Cases ***
${pascal} - Happy Path
    [Documentation]    Verify the ${op.name} endpoint returns HTTP ${method === 'POST' ? '201' : '200'} for a valid request.
    [Tags]    smoke    ${snake}    regression
${isGetter ? '' : `    \${payload}=    Create Dictionary
${requestDict}
`}
    \${response}=    ${method}    ${endpoint}
    ...    ${isGetter ? '' : 'json=${payload}\n    ...    '}headers=\${{'Content-Type': '\${CONTENT_TYPE}'}}
    ...    expected_status=${method === 'POST' ? '201' : '200'}

    Log    Response: \${response.json()}
${responseAssertions}

${pascal} - Validate Response Schema
    [Documentation]    Verify the response body has all expected fields.
    [Tags]    schema    ${snake}
${isGetter ? '' : `    \${payload}=    Create Dictionary
${requestDict}
`}
    \${response}=    ${method}    ${endpoint}
    ...    ${isGetter ? '' : 'json=${payload}\n    ...    '}headers=\${{'Content-Type': '\${CONTENT_TYPE}'}}
    ...    expected_status=${method === 'POST' ? '201' : '200'}

    \${body}=    Set Variable    \${response.json()}
    Should Not Be None    \${body}
${op.outputFields
  .slice(0, 5)
  .map((f) => `    Dictionary Should Contain Key    \${body}    ${toSnake(f.name)}`)
  .join('\n')}

${pascal} - Unauthorised Returns 401
    [Documentation]    Requests without valid credentials must be rejected.
    [Tags]    security    ${snake}
    \${response}=    ${method}    ${endpoint}
    ...    headers=\${{'Content-Type': '\${CONTENT_TYPE}', 'Authorization': '******'}}
    ...    expected_status=401

*** Keywords ***
${pascal} Request Should Succeed
    [Documentation]    Reusable keyword: performs the ${op.name} call and returns the response body.
    [Arguments]    ${isGetter ? '' : `\${payload}`}
    \${response}=    ${method}    ${endpoint}
    ...    ${isGetter ? '' : 'json=${payload}\n    ...    '}expected_status=${method === 'POST' ? '201' : '200'}
    RETURN    \${response.json()}
`;
}
