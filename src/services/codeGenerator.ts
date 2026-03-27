import type { WsdlOperation, WsdlField, GeneratedFiles } from '../types';

// ── helpers ──────────────────────────────────────────────────────────────────

/** Convert camelCase / PascalCase to kebab-case REST path segment */
function toKebab(name: string): string {
  return name
    .replace(/([A-Z])/g, (_, c, i) => (i > 0 ? '-' : '') + c.toLowerCase())
    .replace(/^-/, '');
}

/** Ensure a name starts with an uppercase letter (PascalCase) */
function toPascal(name: string): string {
  return name.charAt(0).toUpperCase() + name.slice(1);
}

/** Ensure a name starts with a lowercase letter (camelCase) */
function toCamel(name: string): string {
  return name.charAt(0).toLowerCase() + name.slice(1);
}

/**
 * Derive whether an operation is a GET (query) or POST (command) based on
 * its name prefix.
 */
function httpMethod(opName: string): 'GET' | 'POST' | 'PUT' | 'DELETE' {
  const lower = opName.toLowerCase();
  if (lower.startsWith('get') || lower.startsWith('list') || lower.startsWith('find') || lower.startsWith('fetch') || lower.startsWith('query') || lower.startsWith('search')) return 'GET';
  if (lower.startsWith('delete') || lower.startsWith('remove')) return 'DELETE';
  if (lower.startsWith('update') || lower.startsWith('modify') || lower.startsWith('change') || lower.startsWith('set')) return 'PUT';
  return 'POST';
}

/** Map Java type to a sample value for use in tests */
function sampleValue(javaType: string, fieldName: string): string {
  const t = javaType.replace('List<', '').replaceAll('>', '');
  if (t === 'String') return `"test${toPascal(fieldName)}"`;
  if (t === 'Integer' || t === 'int') return '1';
  if (t === 'Long' || t === 'long') return '1L';
  if (t === 'Boolean' || t === 'boolean') return 'true';
  if (t === 'Double') return '1.0';
  if (t === 'Float') return '1.0f';
  if (t === 'BigDecimal') return 'BigDecimal.ONE';
  if (t === 'LocalDateTime') return 'LocalDateTime.now()';
  if (t === 'LocalDate') return 'LocalDate.now()';
  if (javaType.startsWith('List<')) return `List.of(${sampleValue(t, fieldName)})`;
  return 'null';
}

/** Detect if any field uses BigDecimal (needs import) */
function needsBigDecimal(fields: WsdlField[]): boolean {
  return fields.some((f) => f.type.includes('BigDecimal'));
}

function needsLocalDateTime(fields: WsdlField[]): boolean {
  return fields.some((f) => f.type.includes('LocalDateTime'));
}

function needsLocalDate(fields: WsdlField[]): boolean {
  return fields.some(
    (f) => f.type.includes('LocalDate') && !f.type.includes('LocalDateTime'),
  );
}

function needsList(fields: WsdlField[]): boolean {
  return fields.some((f) => f.type.startsWith('List<'));
}

// ── extra imports for DTO ──────────────────────────────────────────────────

function dtoImports(fields: WsdlField[]): string {
  const lines: string[] = [];
  if (needsBigDecimal(fields)) lines.push('import java.math.BigDecimal;');
  if (needsLocalDateTime(fields))
    lines.push('import java.time.LocalDateTime;');
  if (needsLocalDate(fields)) lines.push('import java.time.LocalDate;');
  if (needsList(fields)) lines.push('import java.util.List;');
  return lines.join('\n');
}

function testImports(fields: WsdlField[]): string {
  const lines: string[] = [];
  if (needsBigDecimal(fields)) lines.push('import java.math.BigDecimal;');
  if (needsLocalDateTime(fields))
    lines.push('import java.time.LocalDateTime;');
  if (needsLocalDate(fields)) lines.push('import java.time.LocalDate;');
  if (needsList(fields)) lines.push('import java.util.List;');
  return lines.join('\n');
}

// ── field renderers ───────────────────────────────────────────────────────

function renderDtoFields(fields: WsdlField[]): string {
  if (!fields.length) return '    // No fields extracted from WSDL — add fields as needed\n    private String placeholder;';
  return fields
    .map((f) => {
      const validation = f.required
        ? f.type === 'String'
          ? '    @NotBlank\n'
          : '    @NotNull\n'
        : '';
      return `${validation}    private ${f.type} ${toCamel(f.name)};`;
    })
    .join('\n\n');
}

function renderSampleBuilderFields(fields: WsdlField[]): string {
  if (!fields.length) return `            .placeholder("test")`;
  return fields
    .map((f) => `            .${toCamel(f.name)}(${sampleValue(f.type, f.name)})`)
    .join('\n');
}

// ── code generators ───────────────────────────────────────────────────────

export function generateRequestDto(op: WsdlOperation, pkg: string): string {
  const className = `${toPascal(op.name)}Request`;
  const extraImports = dtoImports(op.inputFields);
  const hasRequired = op.inputFields.some((f) => f.required);

  return `package ${pkg}.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;${extraImports ? '\n' + extraImports : ''}${hasRequired ? '\nimport jakarta.validation.constraints.NotBlank;\nimport jakarta.validation.constraints.NotNull;' : ''}

/**
 * REST request DTO for the {@code ${op.name}} N-Central WSDL operation.
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class ${className} {

${renderDtoFields(op.inputFields)}
}
`;
}

export function generateResponseDto(op: WsdlOperation, pkg: string): string {
  const className = `${toPascal(op.name)}Response`;
  const extraImports = dtoImports(op.outputFields);

  return `package ${pkg}.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;${extraImports ? '\n' + extraImports : ''}

/**
 * REST response DTO for the {@code ${op.name}} N-Central WSDL operation.
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class ${className} {

${renderDtoFields(op.outputFields)}
}
`;
}

export function generateServiceInterface(op: WsdlOperation, pkg: string): string {
  const pascal = toPascal(op.name);
  const camel = toCamel(op.name);
  const method = httpMethod(op.name);
  const isGetter = method === 'GET';

  return `package ${pkg}.service;

import ${pkg}.dto.${pascal}Request;
import ${pkg}.dto.${pascal}Response;

/**
 * Service interface for the {@code ${op.name}} N-Central WSDL operation.
 *
 * <p>Implementations are responsible for delegating to the N-Central SOAP
 * client and translating results into REST-friendly response objects.</p>
 */
public interface ${pascal}Service {

    /**
     * ${isGetter ? 'Retrieve' : 'Execute'} the {@code ${op.name}} operation.
     *
     * @param request the REST request DTO
     * @return the REST response DTO
     */
    ${pascal}Response ${camel}(${isGetter ? '' : `${pascal}Request request`});
}
`;
}

export function generateServiceImpl(op: WsdlOperation, pkg: string): string {
  const pascal = toPascal(op.name);
  const camel = toCamel(op.name);
  const method = httpMethod(op.name);
  const isGetter = method === 'GET';

  return `package ${pkg}.service.impl;

import ${pkg}.dto.${pascal}Request;
import ${pkg}.dto.${pascal}Response;
import ${pkg}.service.${pascal}Service;
import ${pkg}.transformer.${pascal}Transformer;
import com.ncentral.ncentral.client.NCentralSoapClient;
import com.ncentral.ncentral.soap.${pascal}SoapRequest;
import com.ncentral.ncentral.soap.${pascal}SoapResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

/**
 * Implementation of {@link ${pascal}Service}.
 *
 * <p>Delegates to the N-Central SOAP client via {@link NCentralSoapClient}
 * and uses {@link ${pascal}Transformer} to convert between REST and SOAP types.</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ${pascal}ServiceImpl implements ${pascal}Service {

    private final NCentralSoapClient nCentralSoapClient;
    private final ${pascal}Transformer transformer;

    @Override
    public ${pascal}Response ${camel}(${isGetter ? '' : `${pascal}Request request`}) {
        log.info("Executing ${op.name}${isGetter ? '' : ' with request: {}'}", ${isGetter ? '' : 'request'});

        ${isGetter ? '' : `${pascal}SoapRequest soapRequest = transformer.toSoapRequest(request);\n        `}${pascal}SoapResponse soapResponse = nCentralSoapClient.${camel}(${isGetter ? '' : 'soapRequest'});

        ${pascal}Response response = transformer.toResponse(soapResponse);
        log.debug("${op.name} response: {}", response);
        return response;
    }
}
`;
}

export function generateTransformer(op: WsdlOperation, pkg: string): string {
  const pascal = toPascal(op.name);
  const method = httpMethod(op.name);
  const isGetter = method === 'GET';

  const inputFieldMappings = op.inputFields.length
    ? op.inputFields
        .map((f) => `            .${toCamel(f.name)}(request.get${toPascal(f.name)}())`)
        .join('\n')
    : '            // map fields from request';

  const outputFieldMappings = op.outputFields.length
    ? op.outputFields
        .map((f) => `            .${toCamel(f.name)}(soapResponse.get${toPascal(f.name)}())`)
        .join('\n')
    : '            // map fields from soapResponse';

  return `package ${pkg}.transformer;

import ${pkg}.dto.${pascal}Request;
import ${pkg}.dto.${pascal}Response;
import com.ncentral.ncentral.soap.${pascal}SoapRequest;
import com.ncentral.ncentral.soap.${pascal}SoapResponse;
import org.springframework.stereotype.Component;

/**
 * Transformer for the {@code ${op.name}} operation.
 *
 * <p>Converts between REST DTOs ({@link ${pascal}Request} / {@link ${pascal}Response})
 * and the corresponding N-Central SOAP types.</p>
 */
@Component
public class ${pascal}Transformer {

${isGetter ? '' : `    /**
     * Converts a REST request DTO to an N-Central SOAP request object.
     */
    public ${pascal}SoapRequest toSoapRequest(${pascal}Request request) {
        return ${pascal}SoapRequest.builder()
${inputFieldMappings}
                .build();
    }

`}    /**
     * Converts an N-Central SOAP response to a REST response DTO.
     */
    public ${pascal}Response toResponse(${pascal}SoapResponse soapResponse) {
        return ${pascal}Response.builder()
${outputFieldMappings}
                .build();
    }
}
`;
}

export function generateController(op: WsdlOperation, pkg: string): string {
  const pascal = toPascal(op.name);
  const camel = toCamel(op.name);
  const method = httpMethod(op.name);
  const endpoint = `/api/v1/${toKebab(op.name)}`;
  const isGetter = method === 'GET';

  const springMethodAnnotation = {
    GET: 'GetMapping',
    POST: 'PostMapping',
    PUT: 'PutMapping',
    DELETE: 'DeleteMapping',
  }[method];

  const requestParam = isGetter
    ? ''
    : `@Valid @RequestBody ${pascal}Request request`;

  const serviceCall = isGetter ? `${camel}()` : `${camel}(request)`;

  const statusImport = method === 'POST' ? '\nimport org.springframework.http.HttpStatus;' : '';
  const responseStatus = method === 'POST' ? '\n    @ResponseStatus(HttpStatus.CREATED)' : '';
  const returnType = method === 'DELETE' ? 'Void' : `${pascal}Response`;

  return `package ${pkg}.controller;

import ${pkg}.dto.${pascal}Request;
import ${pkg}.dto.${pascal}Response;
import ${pkg}.service.${pascal}Service;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;${isGetter ? '' : '\nimport jakarta.validation.Valid;'}
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;${statusImport}
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

/**
 * REST controller exposing the {@code ${op.name}} N-Central WSDL operation
 * as a HTTP ${method} endpoint at {@code ${endpoint}}.
 */
@Slf4j
@RestController
@RequestMapping("/api/v1")
@RequiredArgsConstructor
@Tag(name = "${pascal} API", description = "REST facade for the N-Central ${op.name} WSDL operation")
public class ${pascal}Controller {

    private final ${pascal}Service ${camel}Service;

    @${springMethodAnnotation}("/${toKebab(op.name)}")
    @Operation(
        summary = "${op.name}",
        description = "${op.documentation ?? `REST endpoint wrapping the N-Central ${op.name} WSDL operation.`}"
    )${responseStatus}
    public ResponseEntity<${returnType}> ${camel}(${requestParam}) {
        log.info("Received ${op.name} request${isGetter ? '' : ': {}'}",${isGetter ? '' : ' request,'});
        ${method === 'DELETE' ? `${camel}Service.${serviceCall};\n        return ResponseEntity.noContent().build();` : `${pascal}Response response = ${camel}Service.${serviceCall};\n        return ResponseEntity.${method === 'POST' ? 'status(HttpStatus.CREATED).body' : 'ok'}(response);`}
    }
}
`;
}

export function generateApiClient(op: WsdlOperation, pkg: string): string {
  const pascal = toPascal(op.name);
  const camel = toCamel(op.name);
  const method = httpMethod(op.name);
  const isGetter = method === 'GET';
  const endpoint = `/api/v1/${toKebab(op.name)}`;

  const reqParam = isGetter || method === 'DELETE' ? '' : `${pascal}Request request`;
  const returnType = method === 'DELETE' ? 'Void' : `${pascal}Response`;
  const httpEntityImport = method === 'PUT' ? '\nimport org.springframework.http.HttpEntity;' : '';
  const httpMethodImport = method === 'PUT' ? '\nimport org.springframework.http.HttpMethod;' : '';
  const responseEntityImport = method !== 'DELETE' ? '\nimport org.springframework.http.ResponseEntity;' : '';
  const requestDtoImport = !isGetter && method !== 'DELETE' ? `\nimport ${pkg}.dto.${pascal}Request;` : '';
  const responseDtoImport = method !== 'DELETE' ? `\nimport ${pkg}.dto.${pascal}Response;` : '';

  let httpCall: string;
  if (method === 'GET') {
    httpCall =
      `        log.info("Calling GET ${endpoint}");\n` +
      `        ResponseEntity<${pascal}Response> response =\n` +
      `                restTemplate.getForEntity(baseUrl + "${endpoint}", ${pascal}Response.class);\n` +
      `        return response.getBody();`;
  } else if (method === 'DELETE') {
    httpCall =
      `        log.info("Calling DELETE ${endpoint}");\n` +
      `        restTemplate.delete(baseUrl + "${endpoint}");`;
  } else if (method === 'POST') {
    httpCall =
      `        log.info("Calling POST ${endpoint} with request: {}", request);\n` +
      `        ResponseEntity<${pascal}Response> response =\n` +
      `                restTemplate.postForEntity(baseUrl + "${endpoint}", request, ${pascal}Response.class);\n` +
      `        return response.getBody();`;
  } else {
    httpCall =
      `        log.info("Calling PUT ${endpoint} with request: {}", request);\n` +
      `        HttpEntity<${pascal}Request> entity = new HttpEntity<>(request);\n` +
      `        ResponseEntity<${pascal}Response> response =\n` +
      `                restTemplate.exchange(baseUrl + "${endpoint}", HttpMethod.PUT, entity, ${pascal}Response.class);\n` +
      `        return response.getBody();`;
  }

  return `package ${pkg}.client;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;${httpEntityImport}${httpMethodImport}${responseEntityImport}${requestDtoImport}${responseDtoImport}

/**
 * REST API client for the {@code ${op.name}} endpoint.
 *
 * <p>Inject this bean to call the ${op.name} REST API from another
 * Spring component. Configure the server URL with the
 * {@code api.base-url} property.</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class ${pascal}ApiClient {

    private final RestTemplate restTemplate;

    @Value("\${api.base-url:http://localhost:8080}")
    private String baseUrl;

    /**
     * Calls the ${op.name} REST endpoint.
     *${!isGetter && method !== 'DELETE' ? `\n     * @param request the request body\n     *` : ''}
     * @return the ${pascal}Response from the server
     */
    public ${returnType} ${camel}(${reqParam}) {
${httpCall}
    }
}
`;
}

export function generateJsClient(op: WsdlOperation): string {
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

export function generateAllFiles(op: WsdlOperation, pkg = 'com.ncentral.api'): GeneratedFiles {
  return {
    requestDto: generateRequestDto(op, pkg),
    responseDto: generateResponseDto(op, pkg),
    serviceInterface: generateServiceInterface(op, pkg),
    serviceImpl: generateServiceImpl(op, pkg),
    transformer: generateTransformer(op, pkg),
    controller: generateController(op, pkg),
    apiClient: generateApiClient(op, pkg),
    jsClient: generateJsClient(op),
  };
}

export function generateUnitTests(op: WsdlOperation, pkg = 'com.ncentral.api'): string {
  const pascal = toPascal(op.name);
  const camel = toCamel(op.name);
  const method = httpMethod(op.name);
  const isGetter = method === 'GET';
  const endpoint = `/api/v1/${toKebab(op.name)}`;
  const extraImports = testImports([...op.inputFields, ...op.outputFields]);

  const inputSample = renderSampleBuilderFields(op.inputFields);
  const outputSample = renderSampleBuilderFields(op.outputFields);

  const mockSetup = isGetter
    ? `when(${camel}Service.${camel}()).thenReturn(expectedResponse);`
    : `when(${camel}Service.${camel}(any(${pascal}Request.class))).thenReturn(expectedResponse);`;

  const mockVerify = isGetter
    ? `verify(${camel}Service).${camel}();`
    : `verify(${camel}Service).${camel}(any(${pascal}Request.class));`;

  return `package ${pkg}.service.impl;

import ${pkg}.dto.${pascal}Request;
import ${pkg}.dto.${pascal}Response;
import ${pkg}.transformer.${pascal}Transformer;
import com.ncentral.ncentral.client.NCentralSoapClient;
import com.ncentral.ncentral.soap.${pascal}SoapRequest;
import com.ncentral.ncentral.soap.${pascal}SoapResponse;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;${extraImports ? '\n' + extraImports : ''}

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

/**
 * Unit tests for {@link ${pascal}ServiceImpl}.
 */
@ExtendWith(MockitoExtension.class)
class ${pascal}ServiceImplTest {

    @Mock
    private NCentralSoapClient nCentralSoapClient;

    @Mock
    private ${pascal}Transformer transformer;

    @InjectMocks
    private ${pascal}ServiceImpl serviceImpl;

    // ── Controller slice tests ────────────────────────────────────────────

    @Test
    @DisplayName("${op.name}: successful execution returns expected response")
    void should_return_response_when_${camel}_succeeds() {
        // Arrange
        ${isGetter ? '' : `${pascal}Request request = ${pascal}Request.builder()
${inputSample}
                .build();

        `}${pascal}SoapRequest soapRequest = new ${pascal}SoapRequest();
        ${pascal}SoapResponse soapResponse = new ${pascal}SoapResponse();
        ${pascal}Response expectedResponse = ${pascal}Response.builder()
${outputSample}
                .build();

        ${isGetter ? '' : `when(transformer.toSoapRequest(any(${pascal}Request.class))).thenReturn(soapRequest);\n        `}when(nCentralSoapClient.${camel}(${isGetter ? '' : 'any(${pascal}SoapRequest.class)'})).thenReturn(soapResponse);
        when(transformer.toResponse(any(${pascal}SoapResponse.class))).thenReturn(expectedResponse);

        // Act
        ${pascal}Response actual = serviceImpl.${camel}(${isGetter ? '' : 'request'});

        // Assert
        assertThat(actual).isNotNull();
        assertThat(actual).usingRecursiveComparison().isEqualTo(expectedResponse);
        ${isGetter ? '' : `verify(transformer).toSoapRequest(request);\n        `}verify(nCentralSoapClient).${camel}(${isGetter ? '' : 'soapRequest'});
        verify(transformer).toResponse(soapResponse);
    }

    @Test
    @DisplayName("${op.name}: SOAP client exception propagates")
    void should_propagate_exception_when_soap_client_throws() {
        // Arrange
        ${isGetter ? '' : `${pascal}Request request = ${pascal}Request.builder().build();\n        ${isGetter ? '' : `when(transformer.toSoapRequest(any())).thenReturn(new ${pascal}SoapRequest());\n        `}`}when(nCentralSoapClient.${camel}(${isGetter ? '' : 'any()'}))
                .thenThrow(new RuntimeException("SOAP fault"));

        // Act & Assert
        org.junit.jupiter.api.Assertions.assertThrows(
                RuntimeException.class,
                () -> serviceImpl.${camel}(${isGetter ? '' : 'request'}));
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Controller Test — create as a separate file: ${pascal}ControllerTest.java
// ─────────────────────────────────────────────────────────────────────────────

/*
package ${pkg}.controller;

import ${pkg}.dto.${pascal}Request;
import ${pkg}.dto.${pascal}Response;
import ${pkg}.service.${pascal}Service;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@WebMvcTest(${pascal}Controller.class)
class ${pascal}ControllerTest {

    @Autowired MockMvc mockMvc;
    @Autowired ObjectMapper objectMapper;
    @MockBean ${pascal}Service ${camel}Service;

    @Test
    void should_return_200_for_valid_request() throws Exception {
        ${pascal}Response response = ${pascal}Response.builder()
${outputSample}
                .build();
        ${mockSetup}

        mockMvc.perform(${method.toLowerCase()}("${endpoint}")
                ${isGetter ? '' : `.contentType(MediaType.APPLICATION_JSON)\n                .content(objectMapper.writeValueAsString(${pascal}Request.builder().build()))`})
            .andExpect(status().is${method === 'POST' ? 'Created' : 'Ok'}())
            .andExpect(jsonPath("$").exists());

        ${mockVerify}
    }
}
*/
`;
}

export function generateRobotTests(op: WsdlOperation): string {
  const pascal = toPascal(op.name);
  const camel = toCamel(op.name);
  const method = httpMethod(op.name);
  const endpoint = `/api/v1/${toKebab(op.name)}`;
  const isGetter = method === 'GET';

  const requestDict = op.inputFields.length
    ? op.inputFields
        .map((f) => `    ...    ${toCamel(f.name)}=<${f.type}>`)
        .join('\n')
    : '    ...    # no request body';

  const responseAssertions = op.outputFields.length
    ? op.outputFields
        .slice(0, 3)
        .map(
          (f) =>
            `    Should Not Be Empty    \${response.json()['${toCamel(f.name)}']}`,
        )
        .join('\n')
    : '    Should Not Be Empty    \${response.json()}';

  return `*** Settings ***
Library     Collections
Library     RequestsLibrary
Library     String

Suite Setup    Create Session    ncentral_api    \${BASE_URL}    verify=false

*** Variables ***
\${BASE_URL}         http://localhost:8080
\${CONTENT_TYPE}     application/json
\${AUTH_HEADER}      Bearer \${EMPTY}

*** Test Cases ***
${pascal} - Happy Path
    [Documentation]    Verify the ${op.name} endpoint returns HTTP ${method === 'POST' ? '201' : '200'} for a valid request.
    [Tags]    smoke    ${camel}    regression
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
    [Tags]    schema    ${camel}
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
  .map((f) => `    Dictionary Should Contain Key    \${body}    ${toCamel(f.name)}`)
  .join('\n')}

${pascal} - Unauthorised Returns 401
    [Documentation]    Verify that requests without a valid auth token are rejected.
    [Tags]    security    ${camel}
    \${response}=    ${method}    ${endpoint}
    ...    headers=\${{'Content-Type': '\${CONTENT_TYPE}', 'Authorization': 'Bearer invalid_token'}}
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
