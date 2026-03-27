"""
N-Central API Code Generator — Python / Flask backend
======================================================

Simpler deployment (no Node.js, no build step required):

    pip install -r requirements.txt
    python app.py
    # Open http://localhost:5000

The complete UI is served as a single static HTML file (static/index.html).
All WSDL parsing and code generation runs here in Python, with an optional
LLM proxy endpoint for AI-assisted refinement.

Supported free LLM providers
─────────────────────────────
• Ollama   — local, completely free, no key required
             https://ollama.com
• Groq     — free cloud tier (Llama 3, Mixtral), free API key from
             https://console.groq.com
• Gemini   — free cloud tier (Gemini 1.5 Flash), free API key from
             https://aistudio.google.com
• OpenAI   — paid (kept for compatibility)
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__, static_folder="static")

# ─────────────────────────────────────────────────────────────────────────────
# WSDL Parser
# ─────────────────────────────────────────────────────────────────────────────

XSD_TO_JAVA: dict[str, str] = {
    "string": "String", "normalizedString": "String", "token": "String",
    "int": "Integer", "integer": "Integer", "long": "Long", "short": "Short",
    "byte": "Byte", "double": "Double", "float": "Float", "decimal": "BigDecimal",
    "boolean": "Boolean", "dateTime": "LocalDateTime", "date": "LocalDate",
    "time": "LocalTime", "base64Binary": "byte[]", "anyURI": "String", "anyType": "Object",
}


def _local_tag(el) -> str:
    """Return the local (non-namespaced) tag of an ElementTree element."""
    tag = el.tag
    return tag.split("}")[-1] if "}" in tag else tag


def _children(node, local_tag: str) -> list:
    """All direct children of *node* whose local tag equals *local_tag*."""
    return [c for c in node if _local_tag(c) == local_tag]


def _child(node, local_tag: str):
    """First direct child of *node* whose local tag equals *local_tag*, or None."""
    for c in node:
        if _local_tag(c) == local_tag:
            return c
    return None


def _resolve_local(qname: str) -> str:
    """Strip namespace prefix from a QName, e.g. 'tns:Foo' → 'Foo'."""
    if not qname:
        return ""
    idx = qname.find(":")
    return qname[idx + 1:] if idx >= 0 else qname


def _xsd_to_java(xsd_type: str) -> str:
    return XSD_TO_JAVA.get(_resolve_local(xsd_type), "String")


def _extract_fields(node) -> list[dict]:
    """Recursively extract field dicts from a complexType / sequence / all subtree."""
    if node is None:
        return []
    # Unwrap complexType
    ct = _child(node, "complexType")
    if ct is not None:
        return _extract_fields(ct)
    for seq_tag in ("sequence", "all"):
        seq = _child(node, seq_tag)
        if seq is None:
            continue
        fields: list[dict] = []
        for el in _children(seq, "element"):
            name = _resolve_local(el.get("name") or el.get("ref") or "")
            if not name:
                continue
            raw_type = el.get("type", "")
            java_type = _xsd_to_java(raw_type) if raw_type else "String"
            min_occurs = el.get("minOccurs", "1")
            max_occurs = el.get("maxOccurs", "1")
            nillable = el.get("nillable", "false")
            if _child(el, "complexType") is not None:
                java_type = "Object"
            field_type = f"List<{java_type}>" if max_occurs == "unbounded" else java_type
            required = min_occurs != "0" and nillable not in ("true", "1")
            fields.append({
                "name": name,
                "type": field_type,
                "required": required,
                "maxOccurs": max_occurs if max_occurs != "1" else None,
            })
        return fields
    return []


def _build_schema_map(root) -> dict[str, list[dict]]:
    if root is None:
        return {}
    schema_map: dict[str, list[dict]] = {}
    for el in _children(root, "element"):
        name = el.get("name", "")
        if name:
            schema_map[name] = _extract_fields(el)
    for ct in _children(root, "complexType"):
        name = ct.get("name", "")
        if name:
            schema_map[name] = _extract_fields(ct)
    return schema_map


def parse_wsdl(xml_content: str) -> dict:
    """Parse WSDL XML and return {serviceName, operations}."""
    try:
        root = ET.fromstring(xml_content.strip())
    except ET.ParseError as exc:
        raise ValueError(f"Invalid XML: {exc}") from exc

    defs = root  # root IS the wsdl:definitions element

    # Service name
    service_name = "NCentralService"
    svc = _child(defs, "service")
    if svc is not None:
        service_name = svc.get("name", service_name)

    # Schema map (from wsdl:types → xs:schema)
    types_node = _child(defs, "types")
    schema_map: dict[str, list[dict]] = {}
    if types_node is not None:
        schema_node = _child(types_node, "schema") or types_node
        schema_map = _build_schema_map(schema_node)

    # Message map
    message_map: dict[str, list[dict]] = {}
    for msg in _children(defs, "message"):
        msg_name = msg.get("name", "")
        if not msg_name:
            continue
        fields: list[dict] = []
        for part in _children(msg, "part"):
            element_ref = _resolve_local(part.get("element", ""))
            type_ref = part.get("type", "")
            if element_ref and element_ref in schema_map:
                fields.extend(schema_map[element_ref])
            elif element_ref:
                fields.append({"name": element_ref, "type": "Object", "required": True, "maxOccurs": None})
            elif type_ref:
                part_name = part.get("name", "parameters")
                fields.append({"name": part_name, "type": _xsd_to_java(type_ref), "required": True, "maxOccurs": None})
        message_map[msg_name] = fields

    # Operations from portType
    port_type = _child(defs, "portType")
    operations: list[dict] = []
    if port_type is not None:
        for op_el in _children(port_type, "operation"):
            name = op_el.get("name", "")
            if not name:
                continue
            doc_el = _child(op_el, "documentation")
            documentation = (doc_el.text or "").strip() if doc_el is not None else None
            input_el = _child(op_el, "input")
            output_el = _child(op_el, "output")
            input_msg_ref = _resolve_local(input_el.get("message", "") if input_el is not None else "")
            output_msg_ref = _resolve_local(output_el.get("message", "") if output_el is not None else "")
            operations.append({
                "name": name,
                "documentation": documentation or None,
                "inputMessageName": input_msg_ref or None,
                "outputMessageName": output_msg_ref or None,
                "inputFields": message_map.get(input_msg_ref, []) if input_msg_ref else [],
                "outputFields": message_map.get(output_msg_ref, []) if output_msg_ref else [],
            })

    return {"serviceName": service_name, "operations": operations}


def is_valid_wsdl(content: str) -> bool:
    t = content.strip()
    return t.startswith("<") and ("wsdl:definitions" in t or "<definitions" in t)


# ─────────────────────────────────────────────────────────────────────────────
# Shared naming helpers
# ─────────────────────────────────────────────────────────────────────────────

def _pascal(name: str) -> str:
    return name[0].upper() + name[1:] if name else name


def _camel(name: str) -> str:
    return name[0].lower() + name[1:] if name else name


def _kebab(name: str) -> str:
    s = re.sub(r"([A-Z])", lambda m: "-" + m.group(1).lower(), name)
    return s.lstrip("-")


def _snake(name: str) -> str:
    s = re.sub(r"([A-Z])", lambda m: "_" + m.group(1).lower(), name)
    return s.lstrip("_")


def _http_method(op_name: str) -> str:
    lower = op_name.lower()
    if any(lower.startswith(p) for p in ("get", "list", "find", "fetch", "query", "search")):
        return "GET"
    if any(lower.startswith(p) for p in ("delete", "remove")):
        return "DELETE"
    if any(lower.startswith(p) for p in ("update", "modify", "change", "set")):
        return "PUT"
    return "POST"


# ─────────────────────────────────────────────────────────────────────────────
# Java / Spring Boot 3 Generator
# ─────────────────────────────────────────────────────────────────────────────

def _java_sample(java_type: str, field_name: str) -> str:
    t = java_type.replace("List<", "").replace(">", "")
    if t == "String":
        return f'"test{_pascal(field_name)}"'
    if t in ("Integer", "int"):
        return "1"
    if t in ("Long", "long"):
        return "1L"
    if t in ("Boolean", "boolean"):
        return "true"
    if t == "Double":
        return "1.0"
    if t == "Float":
        return "1.0f"
    if t == "BigDecimal":
        return "BigDecimal.ONE"
    if t == "LocalDateTime":
        return "LocalDateTime.now()"
    if t == "LocalDate":
        return "LocalDate.now()"
    if java_type.startswith("List<"):
        return f"List.of({_java_sample(t, field_name)})"
    return "null"


def _java_dto_imports(fields: list[dict]) -> str:
    types = " ".join(f["type"] for f in fields)
    lines = []
    if "BigDecimal" in types:
        lines.append("import java.math.BigDecimal;")
    if "LocalDateTime" in types:
        lines.append("import java.time.LocalDateTime;")
    if "LocalDate" in types and "LocalDateTime" not in types:
        lines.append("import java.time.LocalDate;")
    if "List<" in types:
        lines.append("import java.util.List;")
    return "\n".join(lines)


def _java_render_fields(fields: list[dict]) -> str:
    if not fields:
        return "    // No fields extracted from WSDL — add fields as needed\n    private String placeholder;"
    parts = []
    for f in fields:
        validation = ""
        if f["required"]:
            validation = "    @NotBlank\n" if f["type"] == "String" else "    @NotNull\n"
        parts.append(f"{validation}    private {f['type']} {_camel(f['name'])};")
    return "\n\n".join(parts)


def _java_builder_fields(fields: list[dict]) -> str:
    if not fields:
        return '            .placeholder("test")'
    return "\n".join(
        f"            .{_camel(f['name'])}({_java_sample(f['type'], f['name'])})"
        for f in fields
    )


def _java_set_fields(fields: list[dict]) -> str:
    """Generate setter calls for a JAX-WS message object (no Lombok builder)."""
    if not fields:
        return "        // no fields to map"
    return "\n".join(
        f"        soapRequest.set{_pascal(f['name'])}(request.get{_pascal(f['name'])}());"
        for f in fields
    )

def java_request_dto(op: dict, pkg: str) -> str:
    pascal = _pascal(op["name"])
    extra = _java_dto_imports(op["inputFields"])
    has_req = any(f["required"] for f in op["inputFields"])
    extra_line = "\n" + extra if extra else ""
    val_imports = (
        "\nimport jakarta.validation.constraints.NotBlank;"
        "\nimport jakarta.validation.constraints.NotNull;"
        if has_req else ""
    )
    fields = _java_render_fields(op["inputFields"])
    return (
        f"package {pkg}.dto;\n\n"
        f"import lombok.AllArgsConstructor;\n"
        f"import lombok.Builder;\n"
        f"import lombok.Data;\n"
        f"import lombok.NoArgsConstructor;{extra_line}{val_imports}\n\n"
        f"/**\n"
        f" * REST request DTO for the {{@code {op['name']}}} N-Central WSDL operation.\n"
        f" */\n"
        f"@Data\n@Builder\n@NoArgsConstructor\n@AllArgsConstructor\n"
        f"public class {pascal}Request {{\n\n{fields}\n}}\n"
    )


def java_response_dto(op: dict, pkg: str) -> str:
    pascal = _pascal(op["name"])
    extra = _java_dto_imports(op["outputFields"])
    extra_line = "\n" + extra if extra else ""
    fields = _java_render_fields(op["outputFields"])
    return (
        f"package {pkg}.dto;\n\n"
        f"import lombok.AllArgsConstructor;\n"
        f"import lombok.Builder;\n"
        f"import lombok.Data;\n"
        f"import lombok.NoArgsConstructor;{extra_line}\n\n"
        f"/**\n"
        f" * REST response DTO for the {{@code {op['name']}}} N-Central WSDL operation.\n"
        f" */\n"
        f"@Data\n@Builder\n@NoArgsConstructor\n@AllArgsConstructor\n"
        f"public class {pascal}Response {{\n\n{fields}\n}}\n"
    )


def java_service_interface(op: dict, pkg: str) -> str:
    pascal = _pascal(op["name"])
    camel = _camel(op["name"])
    is_getter = _http_method(op["name"]) == "GET"
    param = "" if is_getter else f"{pascal}Request request"
    action = "Retrieve" if is_getter else "Execute"
    return (
        f"package {pkg}.service;\n\n"
        f"import {pkg}.dto.{pascal}Request;\n"
        f"import {pkg}.dto.{pascal}Response;\n\n"
        f"/**\n"
        f" * Service interface for the {{@code {op['name']}}} N-Central WSDL operation.\n"
        f" */\n"
        f"public interface {pascal}Service {{\n\n"
        f"    /**\n"
        f"     * {action} the {{@code {op['name']}}} operation.\n"
        f"     *\n"
        f"     * @param request the REST request DTO\n"
        f"     * @return the REST response DTO\n"
        f"     */\n"
        f"    {pascal}Response {camel}({param});\n}}\n"
    )


def java_service_impl(op: dict, pkg: str) -> str:
    pascal = _pascal(op["name"])
    camel = _camel(op["name"])
    method = _http_method(op["name"])
    is_getter = method == "GET"
    param = "" if is_getter else f"{pascal}Request request"
    soap_req = "" if is_getter else f"{pascal}RequestMsg soapRequest = transformer.toSoapRequest(request);\n        "
    soap_arg = "" if is_getter else "soapRequest"
    log_req = "" if is_getter else " with request: {}"
    log_arg = "" if is_getter else ", request"
    req_msg_import = (
        f"\nimport com.nable.n_central.ncentral.ws.{pascal}RequestMsg;"
        if not is_getter else ""
    )
    # Only import REST request DTO when it's actually used in the method signature
    req_dto_import = (
        f"import {pkg}.dto.{pascal}Request;\n"
        if not is_getter else ""
    )
    return (
        f"package {pkg}.service.impl;\n\n"
        f"{req_dto_import}"
        f"import {pkg}.dto.{pascal}Response;\n"
        f"import {pkg}.dto.{pascal}SoapUI;\n"
        f"import {pkg}.service.{pascal}Service;\n"
        f"import {pkg}.transformer.{pascal}Transformer;\n"
        f"import com.nable.n_central.ncentral.ws.{pascal}ResponseMsg;{req_msg_import}\n"
        f"import lombok.RequiredArgsConstructor;\n"
        f"import lombok.extern.slf4j.Slf4j;\n"
        f"import org.springframework.stereotype.Service;\n\n"
        f"/**\n"
        f" * Implementation of {{@link {pascal}Service}}.\n"
        f" */\n"
        f"@Slf4j\n@Service\n@RequiredArgsConstructor\n"
        f"public class {pascal}ServiceImpl implements {pascal}Service {{\n\n"
        f"    private final {pascal}SoapUI soapClient;\n"
        f"    private final {pascal}Transformer transformer;\n\n"
        f"    @Override\n"
        f"    public {pascal}Response {camel}({param}) {{\n"
        f'        log.info("Executing {op["name"]}{log_req}"{log_arg});\n\n'
        f"        {soap_req}{pascal}ResponseMsg soapResponse = soapClient.{camel}({soap_arg});\n\n"
        f"        {pascal}Response response = transformer.toResponse(soapResponse);\n"
        f'        log.debug("{op["name"]} response: {{}}", response);\n'
        f"        return response;\n"
        f"    }}\n}}\n"
    )


def java_transformer(op: dict, pkg: str) -> str:
    pascal = _pascal(op["name"])
    is_getter = _http_method(op["name"]) == "GET"
    in_map = "\n".join(
        f"            .{_camel(f['name'])}(request.get{_pascal(f['name'])}())"
        for f in op["inputFields"]
    ) or "            // map fields from request"
    out_map = "\n".join(
        f"            .{_camel(f['name'])}(soapResponse.get{_pascal(f['name'])}())"
        for f in op["outputFields"]
    ) or "            // map fields from soapResponse"

    req_msg_import = (
        f"\nimport com.nable.n_central.ncentral.ws.{pascal}RequestMsg;"
        if not is_getter else ""
    )
    # Only import the REST request DTO when there's a toSoapRequest method
    req_dto_import = (
        f"import {pkg}.dto.{pascal}Request;\n"
        if not is_getter else ""
    )

    to_soap = "" if is_getter else (
        f"    /**\n"
        f"     * Converts a REST request DTO to a JAX-WS SOAP request message.\n"
        f"     */\n"
        f"    public {pascal}RequestMsg toSoapRequest({pascal}Request request) {{\n"
        f"        {pascal}RequestMsg soapRequest = new {pascal}RequestMsg();\n"
        f"{_java_set_fields(op['inputFields'])}\n"
        f"        return soapRequest;\n"
        f"    }}\n\n"
    )
    return (
        f"package {pkg}.transformer;\n\n"
        f"{req_dto_import}"
        f"import {pkg}.dto.{pascal}Response;\n"
        f"import com.nable.n_central.ncentral.ws.{pascal}ResponseMsg;{req_msg_import}\n"
        f"import org.springframework.stereotype.Component;\n\n"
        f"/**\n"
        f" * Transformer for the {{@code {op['name']}}} operation.\n"
        f" *\n"
        f" * <p>Converts between the REST DTO layer and the JAX-WS generated\n"
        f" * N-Central SOAP message types.</p>\n"
        f" */\n"
        f"@Component\n"
        f"public class {pascal}Transformer {{\n\n"
        f"{to_soap}"
        f"    /**\n"
        f"     * Converts a JAX-WS SOAP response message to a REST response DTO.\n"
        f"     */\n"
        f"    public {pascal}Response toResponse({pascal}ResponseMsg soapResponse) {{\n"
        f"        return {pascal}Response.builder()\n"
        f"{out_map}\n"
        f"                .build();\n"
        f"    }}\n}}\n"
    )


def java_controller(op: dict, pkg: str) -> str:
    pascal = _pascal(op["name"])
    camel = _camel(op["name"])
    method = _http_method(op["name"])
    is_getter = method == "GET"
    endpoint = f"/api/v1/{_kebab(op['name'])}"
    mapping = {"GET": "GetMapping", "POST": "PostMapping", "PUT": "PutMapping", "DELETE": "DeleteMapping"}[method]
    req_param = "" if is_getter else f"@Valid @RequestBody {pascal}Request request"
    service_call = f"{camel}()" if is_getter else f"{camel}(request)"
    status_import = "\nimport org.springframework.http.HttpStatus;" if method == "POST" else ""
    res_status = "\n    @ResponseStatus(HttpStatus.CREATED)" if method == "POST" else ""
    valid_import = "\nimport jakarta.validation.Valid;" if not is_getter else ""
    log_req = "" if is_getter else ": {}"
    log_arg = "" if is_getter else ", request,"
    if method == "DELETE":
        body = f"{camel}Service.{service_call};\n        return ResponseEntity.noContent().build();"
        return_type = "Void"
    elif method == "POST":
        body = f"{pascal}Response response = {camel}Service.{service_call};\n        return ResponseEntity.status(HttpStatus.CREATED).body(response);"
        return_type = f"{pascal}Response"
    else:
        body = f"{pascal}Response response = {camel}Service.{service_call};\n        return ResponseEntity.ok(response);"
        return_type = f"{pascal}Response"
    doc = (op.get("documentation") or f"REST endpoint wrapping the N-Central {op['name']} WSDL operation.").replace('"', "'")
    return (
        f"package {pkg}.controller;\n\n"
        f"import {pkg}.dto.{pascal}Request;\n"
        f"import {pkg}.dto.{pascal}Response;\n"
        f"import {pkg}.service.{pascal}Service;\n"
        f"import io.swagger.v3.oas.annotations.Operation;\n"
        f"import io.swagger.v3.oas.annotations.tags.Tag;{valid_import}\n"
        f"import lombok.RequiredArgsConstructor;\n"
        f"import lombok.extern.slf4j.Slf4j;{status_import}\n"
        f"import org.springframework.http.ResponseEntity;\n"
        f"import org.springframework.web.bind.annotation.*;\n\n"
        f"/**\n"
        f" * REST controller for {{@code {op['name']}}} at {{@code {endpoint}}}.\n"
        f" */\n"
        f"@Slf4j\n@RestController\n@RequestMapping(\"/api/v1\")\n@RequiredArgsConstructor\n"
        f"@Tag(name = \"{pascal} API\", description = \"REST facade for the N-Central {op['name']} WSDL operation\")\n"
        f"public class {pascal}Controller {{\n\n"
        f"    private final {pascal}Service {camel}Service;\n\n"
        f"    @{mapping}(\"/{_kebab(op['name'])}\")\n"
        f"    @Operation(\n"
        f"        summary = \"{op['name']}\",\n"
        f"        description = \"{doc}\"\n"
        f"    ){res_status}\n"
        f"    public ResponseEntity<{return_type}> {camel}({req_param}) {{\n"
        f'        log.info("Received {op["name"]} request{log_req}",{log_arg});\n'
        f"        {body}\n"
        f"    }}\n}}\n"
    )


def java_soap_ui_client(op: dict, pkg: str) -> str:
    """Generate a SoapUI-style direct SOAP client component for the operation.

    Follows the pattern of DeviceAddSoapUI.java in the nable-nc/api-service
    repository: a thin Spring @Component in the dto package that injects the
    JAX-WS generated NcentralWebServicePortType and delegates each SOAP call
    directly to the port type using the WSDL-generated message types.
    """
    pascal = _pascal(op["name"])
    camel = _camel(op["name"])
    method = _http_method(op["name"])
    is_getter = method == "GET"

    # Parameter and return for the SOAP method
    soap_req_type = f"{pascal}RequestMsg"
    soap_res_type = f"{pascal}ResponseMsg"
    req_param = "" if is_getter else f"{soap_req_type} request"
    soap_call = f"nCentralWS.{camel}({'' if is_getter else 'request'})"

    if is_getter:
        method_body = (
            f"        log.info(\"Invoking N-Central SOAP operation: {op['name']}\");\n"
            f"        return {soap_call};"
        )
    else:
        method_body = (
            f"        log.info(\"Invoking N-Central SOAP operation: {op['name']}\");\n"
            f"        {soap_res_type} response = {soap_call};\n"
            f"        log.debug(\"{op['name']} SOAP response: {{}}\", response);\n"
            f"        return response;"
        )

    req_import = (
        f"\nimport com.nable.n_central.ncentral.ws.{pascal}RequestMsg;"
        if not is_getter else ""
    )

    return (
        f"package {pkg}.dto;\n\n"
        f"import com.nable.n_central.ncentral.ws.NcentralWebServicePortType;{req_import}\n"
        f"import com.nable.n_central.ncentral.ws.{pascal}ResponseMsg;\n"
        f"import lombok.RequiredArgsConstructor;\n"
        f"import lombok.extern.slf4j.Slf4j;\n"
        f"import org.springframework.stereotype.Component;\n\n"
        f"/**\n"
        f" * Direct SOAP client for the {{@code {op['name']}}} N-Central WSDL operation.\n"
        f" *\n"
        f" * <p>This component delegates directly to the JAX-WS generated\n"
        f" * {{@link NcentralWebServicePortType}} port type, making it the single\n"
        f" * point of contact between the service layer and the N-Central SOAP API\n"
        f" * for this operation.</p>\n"
        f" *\n"
        f" * <p>Follows the SoapUI client pattern used in the N-Central API service.</p>\n"
        f" */\n"
        f"@Slf4j\n"
        f"@Component\n"
        f"@RequiredArgsConstructor\n"
        f"public class {pascal}SoapUI {{\n\n"
        f"    private final NcentralWebServicePortType nCentralWS;\n\n"
        f"    /**\n"
        f"     * Invokes the {{@code {op['name']}}} SOAP operation on the N-Central server.\n"
        + (f"     *\n     * @param request the JAX-WS generated SOAP request message\n" if not is_getter else "")
        + f"     * @return the JAX-WS generated SOAP response message\n"
        f"     */\n"
        f"    public {soap_res_type} {camel}({req_param}) {{\n"
        f"{method_body}\n"
        f"    }}\n}}\n"
    )


def js_api_client(op: dict) -> str:
    """Generate a vanilla JavaScript (fetch) REST API client for the operation."""
    pascal = _pascal(op["name"])
    camel = _camel(op["name"])
    method = _http_method(op["name"])
    is_getter = method == "GET"
    endpoint = f"/api/v1/{_kebab(op['name'])}"

    has_body = not is_getter and method != "DELETE"

    if has_body:
        fetch_call = (
            f"  const response = await fetch(`${{baseUrl}}{endpoint}`, {{\n"
            f"    method: '{method}',\n"
            f"    headers: {{ 'Content-Type': 'application/json', ...headers }},\n"
            f"    body: JSON.stringify(request),\n"
            f"  }});"
        )
        jsdoc_param = f" * @param {{object}} request  The request body matching the {pascal}Request schema.\n"
        func_params = "request, { baseUrl = 'http://localhost:8080', headers = {} } = {}"
    else:
        fetch_call = (
            f"  const response = await fetch(`${{baseUrl}}{endpoint}`, {{\n"
            f"    method: '{method}',\n"
            f"    headers: {{ 'Content-Type': 'application/json', ...headers }},\n"
            f"  }});"
        )
        jsdoc_param = ""
        func_params = "{ baseUrl = 'http://localhost:8080', headers = {} } = {}"

    if method == "DELETE":
        resolve_block = "  // DELETE returns no body"
        return_type_doc = " * @returns {Promise<void>}"
    else:
        resolve_block = "  return response.json();"
        return_type_doc = f" * @returns {{Promise<object>}} The {pascal}Response JSON object."

    return (
        f"/**\n"
        f" * JavaScript REST API client for the {op['name']} endpoint.\n"
        f" *\n"
        f" * Generated from the N-Central WSDL operation '{op['name']}'.\n"
        f" * Drop this file into any JS/TS project — no dependencies required.\n"
        f" *\n"
        f" * @example\n"
        f" * import {{ {camel} }} from './{_snake(op['name'])}_client.js';\n"
        f" *\n"
        f" * // Usage:\n"
        f" * const result = await {camel}({f'request, ' if has_body else ''}{{ baseUrl: 'https://your-api-host' }});\n"
        f" * console.log(result);\n"
        f" */\n\n"
        f"'use strict';\n\n"
        f"/**\n"
        f" * Call the {op['name']} REST endpoint.\n"
        f" *\n"
        f"{jsdoc_param}"
        f" * @param {{string}} [options.baseUrl]   Base URL of the REST server (default: 'http://localhost:8080').\n"
        f" * @param {{object}} [options.headers]   Extra HTTP headers to include.\n"
        f" {return_type_doc}\n"
        f" * @throws {{Error}} When the server returns a non-OK HTTP status.\n"
        f" */\n"
        f"export async function {camel}({func_params}) {{\n"
        f"{fetch_call}\n\n"
        f"  if (!response.ok) {{\n"
        f"    const errorText = await response.text().catch(() => response.statusText);\n"
        f"    throw new Error(`{op['name']} failed: ${{response.status}} ${{errorText}}`);\n"
        f"  }}\n\n"
        f"  {resolve_block}\n"
        f"}}\n"
    )


def java_generate_all(op: dict, pkg: str = "com.ncentral.api") -> dict:
    return {
        "requestDto": java_request_dto(op, pkg),
        "responseDto": java_response_dto(op, pkg),
        "serviceInterface": java_service_interface(op, pkg),
        "serviceImpl": java_service_impl(op, pkg),
        "transformer": java_transformer(op, pkg),
        "controller": java_controller(op, pkg),
        "apiClient": java_soap_ui_client(op, pkg),
        "jsClient": js_api_client(op),
    }


def java_unit_tests(op: dict, pkg: str = "com.ncentral.api") -> str:
    pascal = _pascal(op["name"])
    camel = _camel(op["name"])
    method = _http_method(op["name"])
    is_getter = method == "GET"
    extra = _java_dto_imports(op["inputFields"] + op["outputFields"])
    in_sample = _java_builder_fields(op["inputFields"])
    out_sample = _java_builder_fields(op["outputFields"])
    req_arrange = (
        "" if is_getter else
        f"{pascal}Request request = {pascal}Request.builder()\n{in_sample}\n                .build();\n\n        "
    )
    soap_req_stub = (
        "" if is_getter else
        f"when(transformer.toSoapRequest(any({pascal}Request.class))).thenReturn(soapRequest);\n        "
    )
    soap_call_arg = "" if is_getter else f"any({pascal}RequestMsg.class)"
    verify_req = (
        "" if is_getter else
        f"verify(transformer).toSoapRequest(request);\n        "
    )
    actual_call = f"serviceImpl.{camel}()" if is_getter else f"serviceImpl.{camel}(request)"
    req_except = (
        "" if is_getter else
        f"{pascal}Request request = {pascal}Request.builder().build();\n        "
        f"when(transformer.toSoapRequest(any())).thenReturn(new {pascal}RequestMsg());\n        "
    )
    except_call = f"serviceImpl.{camel}()" if is_getter else f"serviceImpl.{camel}(request)"
    extra_line = "\n" + extra if extra else ""
    req_msg_import = (
        f"\nimport com.nable.n_central.ncentral.ws.{pascal}RequestMsg;"
        if not is_getter else ""
    )
    return (
        f"package {pkg}.service.impl;\n\n"
        f"import {pkg}.dto.{pascal}Request;\n"
        f"import {pkg}.dto.{pascal}Response;\n"
        f"import {pkg}.dto.{pascal}SoapUI;\n"
        f"import {pkg}.transformer.{pascal}Transformer;\n"
        f"import com.nable.n_central.ncentral.ws.{pascal}ResponseMsg;{req_msg_import}\n"
        f"import org.junit.jupiter.api.DisplayName;\n"
        f"import org.junit.jupiter.api.Test;\n"
        f"import org.junit.jupiter.api.extension.ExtendWith;\n"
        f"import org.mockito.InjectMocks;\n"
        f"import org.mockito.Mock;\n"
        f"import org.mockito.junit.jupiter.MockitoExtension;{extra_line}\n\n"
        f"import static org.assertj.core.api.Assertions.assertThat;\n"
        f"import static org.mockito.ArgumentMatchers.any;\n"
        f"import static org.mockito.Mockito.*;\n\n"
        f"/** Unit tests for {{@link {pascal}ServiceImpl}}. */\n"
        f"@ExtendWith(MockitoExtension.class)\n"
        f"class {pascal}ServiceImplTest {{\n\n"
        f"    @Mock\n    private {pascal}SoapUI soapClient;\n"
        f"    @Mock\n    private {pascal}Transformer transformer;\n"
        f"    @InjectMocks\n    private {pascal}ServiceImpl serviceImpl;\n\n"
        f"    @Test\n"
        f"    @DisplayName(\"{op['name']}: successful execution returns expected response\")\n"
        f"    void should_return_response_when_{camel}_succeeds() {{\n"
        f"        // Arrange\n"
        f"        {req_arrange}"
        + (f"{pascal}RequestMsg soapRequest = new {pascal}RequestMsg();\n        " if not is_getter else "")
        + f"{pascal}ResponseMsg soapResponse = new {pascal}ResponseMsg();\n"
        f"        {pascal}Response expectedResponse = {pascal}Response.builder()\n"
        f"{out_sample}\n"
        f"                .build();\n\n"
        f"        {soap_req_stub}when(soapClient.{camel}({soap_call_arg})).thenReturn(soapResponse);\n"
        f"        when(transformer.toResponse(any({pascal}ResponseMsg.class))).thenReturn(expectedResponse);\n\n"
        f"        // Act\n"
        f"        {pascal}Response actual = {actual_call};\n\n"
        f"        // Assert\n"
        f"        assertThat(actual).isNotNull();\n"
        f"        assertThat(actual).usingRecursiveComparison().isEqualTo(expectedResponse);\n"
        f"        {verify_req}verify(soapClient).{camel}({'soapRequest' if not is_getter else ''});\n"
        f"        verify(transformer).toResponse(soapResponse);\n"
        f"    }}\n\n"
        f"    @Test\n"
        f"    @DisplayName(\"{op['name']}: SOAP client exception propagates\")\n"
        f"    void should_propagate_exception_when_soap_client_throws() {{\n"
        f"        {req_except}when(soapClient.{camel}({'any()' if not is_getter else ''})).thenThrow(new RuntimeException(\"SOAP fault\"));\n\n"
        f"        org.junit.jupiter.api.Assertions.assertThrows(\n"
        f"                RuntimeException.class,\n"
        f"                () -> {except_call});\n"
        f"    }}\n}}\n"
    )


def java_robot_tests(op: dict) -> str:
    pascal = _pascal(op["name"])
    camel = _camel(op["name"])
    method = _http_method(op["name"])
    is_getter = method == "GET"
    endpoint = f"/api/v1/{_kebab(op['name'])}"
    status = "201" if method == "POST" else "200"
    req_dict = "\n".join(f"    ...    {_camel(f['name'])}=<{f['type']}>" for f in op["inputFields"]) or "    ...    # no request body"
    resp_asserts = "\n".join(
        f"    Should Not Be Empty    ${{response.json()['{_camel(f['name'])}'] }}"
        for f in op["outputFields"][:3]
    ) or "    Should Not Be Empty    ${response.json()}"
    schema_keys = "\n".join(
        f"    Dictionary Should Contain Key    ${{body}}    {_camel(f['name'])}"
        for f in op["outputFields"][:5]
    )
    payload_block = "" if is_getter else f"    ${{payload}}=    Create Dictionary\n{req_dict}\n"
    json_header = "" if is_getter else "json=${payload}\n    ...    "
    return (
        f"*** Settings ***\n"
        f"Library     Collections\n"
        f"Library     RequestsLibrary\n"
        f"Library     String\n\n"
        f"Suite Setup    Create Session    ncentral_api    ${{BASE_URL}}    verify=false\n\n"
        f"*** Variables ***\n"
        f"${{BASE_URL}}         http://localhost:8080\n"
        f"${{CONTENT_TYPE}}     application/json\n\n"
        f"*** Test Cases ***\n"
        f"{pascal} - Happy Path\n"
        f"    [Documentation]    Verify {op['name']} returns HTTP {status} for a valid request.\n"
        f"    [Tags]    smoke    {camel}    regression\n"
        f"{payload_block}\n"
        f"    ${{response}}=    {method}    {endpoint}\n"
        f"    ...    {json_header}headers=${{'Content-Type': '${{CONTENT_TYPE}}'}}\n"
        f"    ...    expected_status={status}\n\n"
        f"    Log    Response: ${{response.json()}}\n"
        f"{resp_asserts}\n\n"
        f"{pascal} - Validate Response Schema\n"
        f"    [Documentation]    Verify the response body has all expected fields.\n"
        f"    [Tags]    schema    {camel}\n"
        f"{payload_block}\n"
        f"    ${{response}}=    {method}    {endpoint}\n"
        f"    ...    {json_header}headers=${{'Content-Type': '${{CONTENT_TYPE}}'}}\n"
        f"    ...    expected_status={status}\n\n"
        f"    ${{body}}=    Set Variable    ${{response.json()}}\n"
        f"    Should Not Be None    ${{body}}\n"
        f"{schema_keys}\n\n"
        f"*** Keywords ***\n"
        f"{pascal} Request Should Succeed\n"
        f"    [Documentation]    Reusable keyword — performs the {op['name']} call.\n"
        f"    ${{response}}=    {method}    {endpoint}\n"
        f"    ...    {json_header}expected_status={status}\n"
        f"    RETURN    ${{response.json()}}\n"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Python / FastAPI Generator
# ─────────────────────────────────────────────────────────────────────────────

JAVA_TO_PYTHON: dict[str, str] = {
    "String": "str", "Integer": "int", "Long": "int", "Short": "int", "Byte": "int",
    "Double": "float", "Float": "float", "BigDecimal": "Decimal",
    "Boolean": "bool", "LocalDateTime": "datetime", "LocalDate": "date",
    "LocalTime": "time", "byte[]": "bytes", "Object": "Any",
}


def _java_to_py(java_type: str) -> str:
    if java_type.startswith("List<") and java_type.endswith(">"):
        return f"list[{_java_to_py(java_type[5:-1])}]"
    return JAVA_TO_PYTHON.get(java_type, "str")


def _py_imports(fields: list[dict]) -> list[str]:
    imports: set[str] = set()
    for f in fields:
        py = _java_to_py(f["type"])
        if py == "Decimal":
            imports.add("from decimal import Decimal")
        if py == "datetime":
            imports.add("from datetime import datetime")
        if py == "date":
            imports.add("from datetime import date")
        if py == "time":
            imports.add("from datetime import time")
        if py == "Any":
            imports.add("from typing import Any")
        if py.startswith("list["):
            inner = py[5:-1]
            if inner == "datetime":
                imports.add("from datetime import datetime")
            if inner == "date":
                imports.add("from datetime import date")
            if inner == "Decimal":
                imports.add("from decimal import Decimal")
    return sorted(imports)


def _py_render_fields(fields: list[dict]) -> str:
    if not fields:
        return '    placeholder: str = ""  # No fields extracted — add fields as needed'
    parts = []
    for f in fields:
        py_type = _java_to_py(f["type"])
        if not f["required"]:
            parts.append(f"    {_snake(f['name'])}: Optional[{py_type}] = None")
        else:
            parts.append(f"    {_snake(f['name'])}: {py_type}")
    return "\n".join(parts)


def _py_sample(java_type: str, field_name: str) -> str:
    py = _java_to_py(java_type)
    if py == "str":
        return f'"test_{_snake(field_name)}"'
    if py == "int":
        return "1"
    if py == "float":
        return "1.0"
    if py == "bool":
        return "True"
    if py == "Decimal":
        return 'Decimal("1.0")'
    if py == "datetime":
        return "datetime.now()"
    if py == "date":
        return "date.today()"
    if py.startswith("list["):
        return "[]"
    return "None"


def py_request_dto(op: dict) -> str:
    pascal = _pascal(op["name"])
    extra = _py_imports(op["inputFields"])
    has_opt = any(not f["required"] for f in op["inputFields"])
    opt_line = "from typing import Optional\n" if has_opt else ""
    extra_str = "\n" + "\n".join(extra) if extra else ""
    example = "\n".join(
        f'                "{_snake(f["name"])}": {_py_sample(f["type"], f["name"])}'
        for f in op["inputFields"]
    ) or '                "placeholder": ""'
    return (
        f'"""Pydantic request schema for \'{op["name"]}\' N-Central WSDL operation."""\n'
        f"from __future__ import annotations\n\n"
        f"{opt_line}"
        f"from pydantic import BaseModel, Field{extra_str}\n\n\n"
        f"class {pascal}Request(BaseModel):\n"
        f'    """Request body for the {op["name"]} endpoint."""\n\n'
        f"{_py_render_fields(op['inputFields'])}\n\n"
        f"    class Config:\n"
        f"        populate_by_name = True\n"
        f"        json_schema_extra = {{\n"
        f'            "example": {{\n'
        f"{example}\n"
        f"            }}\n"
        f"        }}\n"
    )


def py_response_dto(op: dict) -> str:
    pascal = _pascal(op["name"])
    extra = _py_imports(op["outputFields"])
    has_opt = any(not f["required"] for f in op["outputFields"])
    opt_line = "from typing import Optional\n" if has_opt else ""
    extra_str = "\n" + "\n".join(extra) if extra else ""
    return (
        f'"""Pydantic response schema for \'{op["name"]}\' N-Central WSDL operation."""\n'
        f"from __future__ import annotations\n\n"
        f"{opt_line}"
        f"from pydantic import BaseModel{extra_str}\n\n\n"
        f"class {pascal}Response(BaseModel):\n"
        f'    """Response body for the {op["name"]} endpoint."""\n\n'
        f"{_py_render_fields(op['outputFields'])}\n\n"
        f"    class Config:\n"
        f"        populate_by_name = True\n"
    )


def py_service_base(op: dict) -> str:
    pascal = _pascal(op["name"])
    snake = _snake(op["name"])
    is_getter = _http_method(op["name"]) == "GET"
    param = "self" if is_getter else f"self, request: {pascal}Request"
    action = "Retrieve" if is_getter else "Execute"
    return (
        f'"""Abstract service base class for \'{op["name"]}\' N-Central WSDL operation."""\n'
        f"from __future__ import annotations\n\n"
        f"from abc import ABC, abstractmethod\n\n"
        f"from .schemas import {pascal}Request, {pascal}Response\n\n\n"
        f"class {pascal}ServiceBase(ABC):\n"
        f'    """Abstract base for the {op["name"]} service."""\n\n'
        f"    @abstractmethod\n"
        f"    def {snake}({param}) -> {pascal}Response:\n"
        f"        \"\"\"\n"
        f"        {action} the {op['name']} operation.\n\n"
        f"        Returns:\n"
        f"            A {pascal}Response containing the N-Central SOAP result.\n"
        f"        \"\"\"\n"
        f"        ...\n"
    )


def py_service_impl(op: dict) -> str:
    pascal = _pascal(op["name"])
    snake = _snake(op["name"])
    is_getter = _http_method(op["name"]) == "GET"
    param = "self" if is_getter else f"self, request: {pascal}Request"
    soap_req = "" if is_getter else f"soap_request = self._transformer.to_soap_request(request)\n        "
    soap_arg = "" if is_getter else "soap_request"
    log_req = "" if is_getter else " with request: %s"
    log_arg = "" if is_getter else ", request"
    return (
        f'"""Concrete service implementation for \'{op["name"]}\' N-Central WSDL operation."""\n'
        f"from __future__ import annotations\n\n"
        f"import logging\n\n"
        f"from .schemas import {pascal}Request, {pascal}Response\n"
        f"from .service_base import {pascal}ServiceBase\n"
        f"from .transformer import {pascal}Transformer\n"
        f"from ..soap.client import NCentralSoapClient\n\n"
        f"logger = logging.getLogger(__name__)\n\n\n"
        f"class {pascal}Service({pascal}ServiceBase):\n"
        f"    \"\"\"Implements :class:`{pascal}ServiceBase`.\"\"\"\n\n"
        f"    def __init__(\n"
        f"        self,\n"
        f"        soap_client: NCentralSoapClient,\n"
        f"        transformer: {pascal}Transformer,\n"
        f"    ) -> None:\n"
        f"        self._soap_client = soap_client\n"
        f"        self._transformer = transformer\n\n"
        f"    def {snake}({param}) -> {pascal}Response:\n"
        f'        logger.info("Executing {op["name"]}{log_req}"{log_arg})\n'
        f"        {soap_req}soap_response = self._soap_client.{snake}({soap_arg})\n"
        f"        response = self._transformer.to_response(soap_response)\n"
        f'        logger.debug("{op["name"]} response: %s", response)\n'
        f"        return response\n"
    )


def py_transformer(op: dict) -> str:
    pascal = _pascal(op["name"])
    is_getter = _http_method(op["name"]) == "GET"
    in_map = "\n".join(
        f"            {_snake(f['name'])}=request.{_snake(f['name'])},"
        for f in op["inputFields"]
    ) or "            # map fields from request"
    out_map = "\n".join(
        f"            {_snake(f['name'])}=soap_response.{_snake(f['name'])},"
        for f in op["outputFields"]
    ) or "            # map fields from soap_response"
    to_soap = "" if is_getter else (
        f"    def to_soap_request(self, request: {pascal}Request) -> {pascal}SoapRequest:\n"
        f'        """Convert a REST request DTO to a SOAP request object."""\n'
        f"        return {pascal}SoapRequest(\n"
        f"{in_map}\n"
        f"        )\n\n"
    )
    return (
        f'"""Transformer for \'{op["name"]}\' N-Central WSDL operation."""\n'
        f"from __future__ import annotations\n\n"
        f"from .schemas import {pascal}Request, {pascal}Response\n"
        f"from ..soap.models import {pascal}SoapRequest, {pascal}SoapResponse\n\n\n"
        f"class {pascal}Transformer:\n"
        f'    """Converts between REST DTOs and N-Central SOAP types for {op["name"]}."""\n\n'
        f"{to_soap}"
        f"    def to_response(self, soap_response: {pascal}SoapResponse) -> {pascal}Response:\n"
        f'        """Convert a SOAP response to a REST response DTO."""\n'
        f"        return {pascal}Response(\n"
        f"{out_map}\n"
        f"        )\n"
    )


def py_controller(op: dict) -> str:
    pascal = _pascal(op["name"])
    snake = _snake(op["name"])
    method = _http_method(op["name"])
    is_getter = method == "GET"
    endpoint = f"/{_kebab(op['name'])}"
    http_dec = method.lower()
    status_code = ", status_code=201" if method == "POST" else ""
    request_param = "" if is_getter else f"    request: {pascal}Request,\n"
    service_call = f"{snake}()" if is_getter else f"{snake}(request)"
    response_model = "None" if method == "DELETE" else f"{pascal}Response"
    delete_import = ", Response" if method == "DELETE" else ""
    log_req = "" if is_getter else ": %s"
    log_arg = "" if is_getter else ", request"
    doc = (op.get("documentation") or f"REST endpoint wrapping the N-Central {op['name']} WSDL operation.").replace('"', "'")
    if method == "DELETE":
        handler = (
            f"async def {snake}(\n"
            f"    service: {pascal}Service = Depends(get_{snake}_service),\n"
            f") -> None:\n"
            f'    logger.info("Received {op["name"]} request")\n'
            f"    service.{service_call}\n"
        )
    else:
        handler = (
            f"async def {snake}(\n"
            f"{request_param}"
            f"    service: {pascal}Service = Depends(get_{snake}_service),\n"
            f") -> {pascal}Response:\n"
            f'    logger.info("Received {op["name"]} request{log_req}"{log_arg})\n'
            f"    return service.{service_call}\n"
        )
    return (
        f'"""FastAPI router for \'{op["name"]}\' N-Central WSDL operation."""\n'
        f"from __future__ import annotations\n\n"
        f"import logging\n\n"
        f"from fastapi import APIRouter, Depends{delete_import}\n\n"
        f"from .schemas import {pascal}Request, {pascal}Response\n"
        f"from .service import {pascal}Service\n"
        f"from ..dependencies import get_{snake}_service\n\n"
        f"logger = logging.getLogger(__name__)\n\n"
        f"router = APIRouter(prefix=\"/api/v1\", tags=[\"{pascal}\"])\n\n\n"
        f"@router.{http_dec}(\n"
        f'    "{endpoint}",\n'
        f"    response_model={response_model},\n"
        f'    summary="{op["name"]}",\n'
        f'    description="{doc}"{status_code},\n'
        f")\n"
        f"{handler}"
    )


def py_api_client(op: dict) -> str:
    """Generate an httpx-based typed REST API client for the operation."""
    pascal = _pascal(op["name"])
    snake = _snake(op["name"])
    method = _http_method(op["name"])
    is_getter = method == "GET"
    endpoint = f"/api/v1/{_kebab(op['name'])}"
    has_body = not is_getter and method != "DELETE"

    if method == "GET":
        http_call = (
            f"        response = self._client.get(f\"{{self.base_url}}{endpoint}\")\n"
            f"        response.raise_for_status()\n"
            f"        return {pascal}Response(**response.json())"
        )
    elif method == "DELETE":
        http_call = (
            f"        response = self._client.delete(f\"{{self.base_url}}{endpoint}\")\n"
            f"        response.raise_for_status()"
        )
    elif method == "POST":
        http_call = (
            f"        response = self._client.post(\n"
            f"            f\"{{self.base_url}}{endpoint}\",\n"
            f"            content=request.model_dump_json(),\n"
            f"            headers={{\"Content-Type\": \"application/json\"}},\n"
            f"        )\n"
            f"        response.raise_for_status()\n"
            f"        return {pascal}Response(**response.json())"
        )
    else:  # PUT
        http_call = (
            f"        response = self._client.put(\n"
            f"            f\"{{self.base_url}}{endpoint}\",\n"
            f"            content=request.model_dump_json(),\n"
            f"            headers={{\"Content-Type\": \"application/json\"}},\n"
            f"        )\n"
            f"        response.raise_for_status()\n"
            f"        return {pascal}Response(**response.json())"
        )

    return_type = "None" if method == "DELETE" else f"{pascal}Response"
    param = "self" if is_getter or method == "DELETE" else f"self, request: {pascal}Request"
    schema_import = f"from .schemas import {pascal}Request, {pascal}Response" if has_body else f"from .schemas import {pascal}Response"
    request_import = schema_import if not has_body else schema_import

    return (
        f'"""REST API client for the \'{op["name"]}\' endpoint."""\n'
        f"from __future__ import annotations\n\n"
        f"import httpx\n\n"
        f"{request_import}\n\n\n"
        f"class {pascal}ApiClient:\n"
        f'    """\n'
        f"    Typed HTTP client for the {op['name']} REST endpoint.\n\n"
        f"    Use this class to call the generated REST API from another\n"
        f"    Python service or script.\n\n"
        f"    Example::\n\n"
        f"        with {pascal}ApiClient(base_url=\"http://localhost:8000\") as client:\n"
        f"            {'result = client.' + snake + '()' if is_getter else 'result = client.' + snake + '(request)'}\n"
        f"    \"\"\"\n\n"
        f"    def __init__(self, base_url: str = \"http://localhost:8000\", timeout: float = 30.0) -> None:\n"
        f"        self.base_url = base_url.rstrip(\"/\")\n"
        f"        self._client = httpx.Client(timeout=timeout)\n\n"
        f"    def {snake}({param}) -> {return_type}:\n"
        f'        """\n'
        f"        Call the {op['name']} REST endpoint.\n\n"
        f"        Raises:\n"
        f"            httpx.HTTPStatusError: When the server returns a non-2xx status.\n"
        f'        """\n'
        f"{http_call}\n\n"
        f"    def close(self) -> None:\n"
        f'        """Close the underlying HTTP connection pool."""\n'
        f"        self._client.close()\n\n"
        f"    def __enter__(self) -> \"{pascal}ApiClient\":\n"
        f"        return self\n\n"
        f"    def __exit__(self, *args: object) -> None:\n"
        f"        self.close()\n"
    )


def py_generate_all(op: dict) -> dict:
    return {
        "requestDto": py_request_dto(op),
        "responseDto": py_response_dto(op),
        "serviceInterface": py_service_base(op),
        "serviceImpl": py_service_impl(op),
        "transformer": py_transformer(op),
        "controller": py_controller(op),
        "apiClient": py_api_client(op),
        "jsClient": js_api_client(op),
    }


def py_unit_tests(op: dict) -> str:
    pascal = _pascal(op["name"])
    snake = _snake(op["name"])
    method = _http_method(op["name"])
    is_getter = method == "GET"
    in_sample = "\n".join(
        f"        {_snake(f['name'])}={_py_sample(f['type'], f['name'])},"
        for f in op["inputFields"]
    ) or "        # no input fields"
    out_sample = "\n".join(
        f"        {_snake(f['name'])}={_py_sample(f['type'], f['name'])},"
        for f in op["outputFields"]
    ) or "        # no output fields"
    request_fixture = "" if is_getter else (
        f"\n\n@pytest.fixture()\n"
        f"def sample_request() -> {pascal}Request:\n"
        f"    return {pascal}Request(\n{in_sample}\n    )"
    )
    soap_setup = "" if is_getter else f"transformer.to_soap_request.return_value = {pascal}SoapRequest()\n        "
    soap_assert = "" if is_getter else f"transformer.to_soap_request.assert_called_once_with(request)\n        "
    request_arg = "" if is_getter else "\n        request = sample_request"
    actual_call = f"service.{snake}()" if is_getter else f"service.{snake}(request)"
    sample_req_fixture = "" if is_getter else f"\n        sample_request: {pascal}Request,"
    except_setup = "" if is_getter else f"transformer.to_soap_request.return_value = {pascal}SoapRequest()\n        "
    except_call = f"service.{snake}()" if is_getter else f"service.{snake}({pascal}Request())"
    return (
        f'"""Unit tests for {pascal}Service (pytest + unittest.mock)."""\n'
        f"from __future__ import annotations\n\n"
        f"from unittest.mock import MagicMock\n\n"
        f"import pytest\n\n"
        f"from ..schemas import {pascal}Request, {pascal}Response\n"
        f"from ..service import {pascal}Service\n"
        f"from ..transformer import {pascal}Transformer\n"
        f"from ...soap.client import NCentralSoapClient\n"
        f"from ...soap.models import {pascal}SoapRequest, {pascal}SoapResponse\n\n\n"
        f"@pytest.fixture()\n"
        f"def soap_client() -> MagicMock:\n"
        f"    return MagicMock(spec=NCentralSoapClient)\n\n\n"
        f"@pytest.fixture()\n"
        f"def transformer() -> MagicMock:\n"
        f"    return MagicMock(spec={pascal}Transformer)\n\n\n"
        f"@pytest.fixture()\n"
        f"def service(soap_client: MagicMock, transformer: MagicMock) -> {pascal}Service:\n"
        f"    return {pascal}Service(soap_client=soap_client, transformer=transformer)"
        f"{request_fixture}\n\n\n"
        f"class Test{pascal}Service:\n"
        f"    def test_{snake}_returns_expected_response(\n"
        f"        self,\n"
        f"        service: {pascal}Service,{sample_req_fixture}\n"
        f"        soap_client: MagicMock,\n"
        f"        transformer: MagicMock,\n"
        f"    ) -> None:\n"
        f'        """Happy path: successful execution returns the expected response."""\n'
        f"        # Arrange{request_arg}\n"
        f"        expected_response = {pascal}Response(\n{out_sample}\n        )\n"
        f"        soap_response = {pascal}SoapResponse()\n"
        f"        {soap_setup}soap_client.{snake}.return_value = soap_response\n"
        f"        transformer.to_response.return_value = expected_response\n\n"
        f"        # Act\n"
        f"        result = {actual_call}\n\n"
        f"        # Assert\n"
        f"        assert result == expected_response\n"
        f"        {soap_assert}soap_client.{snake}.assert_called_once()\n"
        f"        transformer.to_response.assert_called_once_with(soap_response)\n\n"
        f"    def test_{snake}_propagates_soap_exception(\n"
        f"        self,\n"
        f"        service: {pascal}Service,\n"
        f"        soap_client: MagicMock,\n"
        f"        transformer: MagicMock,\n"
        f"    ) -> None:\n"
        f'        """SOAP client errors must propagate to the caller."""\n'
        f"        {except_setup}soap_client.{snake}.side_effect = RuntimeError(\"SOAP fault\")\n\n"
        f"        with pytest.raises(RuntimeError, match=\"SOAP fault\"):\n"
        f"            {except_call}\n"
    )


def py_robot_tests(op: dict) -> str:
    pascal = _pascal(op["name"])
    method = _http_method(op["name"])
    is_getter = method == "GET"
    endpoint = f"/api/v1/{_kebab(op['name'])}"
    status = "201" if method == "POST" else "200"
    req_dict = "\n".join(
        f"    ...    {_snake(f['name'])}=<value>" for f in op["inputFields"]
    ) or "    ...    # no request body"
    resp_asserts = "\n".join(
        f"    Should Not Be Empty    ${{response.json()['{_snake(f['name'])}'] }}"
        for f in op["outputFields"][:3]
    ) or "    Should Not Be Empty    ${response.json()}"
    schema_keys = "\n".join(
        f"    Dictionary Should Contain Key    ${{body}}    {_snake(f['name'])}"
        for f in op["outputFields"][:5]
    )
    payload_block = "" if is_getter else f"    ${{payload}}=    Create Dictionary\n{req_dict}\n"
    json_header = "" if is_getter else "json=${payload}\n    ...    "
    return (
        f"*** Settings ***\n"
        f"Library     Collections\n"
        f"Library     RequestsLibrary\n"
        f"Library     String\n\n"
        f"Suite Setup    Create Session    ncentral_api    ${{BASE_URL}}    verify=false\n\n"
        f"*** Variables ***\n"
        f"${{BASE_URL}}         http://localhost:8000\n"
        f"${{CONTENT_TYPE}}     application/json\n\n"
        f"*** Test Cases ***\n"
        f"{pascal} - Happy Path\n"
        f"    [Documentation]    Verify {op['name']} returns HTTP {status}.\n"
        f"    [Tags]    smoke    {_snake(op['name'])}    regression\n"
        f"{payload_block}\n"
        f"    ${{response}}=    {method}    {endpoint}\n"
        f"    ...    {json_header}headers=${{'Content-Type': '${{CONTENT_TYPE}}'}}\n"
        f"    ...    expected_status={status}\n\n"
        f"    Log    Response: ${{response.json()}}\n"
        f"{resp_asserts}\n\n"
        f"{pascal} - Validate Response Schema\n"
        f"    [Documentation]    Verify the response body has all expected fields.\n"
        f"    [Tags]    schema    {_snake(op['name'])}\n"
        f"{payload_block}\n"
        f"    ${{response}}=    {method}    {endpoint}\n"
        f"    ...    {json_header}headers=${{'Content-Type': '${{CONTENT_TYPE}}'}}\n"
        f"    ...    expected_status={status}\n\n"
        f"    ${{body}}=    Set Variable    ${{response.json()}}\n"
        f"    Should Not Be None    ${{body}}\n"
        f"{schema_keys}\n\n"
        f"*** Keywords ***\n"
        f"{pascal} Request Should Succeed\n"
        f"    [Documentation]    Reusable keyword — performs the {op['name']} call.\n"
        f"    ${{response}}=    {method}    {endpoint}\n"
        f"    ...    {json_header}expected_status={status}\n"
        f"    RETURN    ${{response.json()}}\n"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Flask routes
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/parse-wsdl", methods=["POST"])
def api_parse_wsdl():
    body = request.get_json(force=True) or {}
    wsdl_content = (body.get("wsdl") or "").strip()
    if not wsdl_content:
        return jsonify({"error": "No WSDL content provided"}), 400
    if not is_valid_wsdl(wsdl_content):
        return jsonify({"error": "Content does not appear to be a WSDL file (missing <definitions> root)"}), 400
    try:
        result = parse_wsdl(wsdl_content)
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Parse error: {exc}"}), 500


@app.route("/api/generate", methods=["POST"])
def api_generate():
    body = request.get_json(force=True) or {}
    op = body.get("operation")
    lang = body.get("language", "java")
    pkg = body.get("package", "com.ncentral.api")
    if not op:
        return jsonify({"error": "Missing 'operation' field"}), 400
    try:
        files = py_generate_all(op) if lang == "python" else java_generate_all(op, pkg)
        return jsonify({"files": files})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 500


@app.route("/api/generate-tests", methods=["POST"])
def api_generate_tests():
    body = request.get_json(force=True) or {}
    op = body.get("operation")
    lang = body.get("language", "java")
    pkg = body.get("package", "com.ncentral.api")
    if not op:
        return jsonify({"error": "Missing 'operation' field"}), 400
    try:
        if lang == "python":
            unit = py_unit_tests(op)
            robot = py_robot_tests(op)
        else:
            unit = java_unit_tests(op, pkg)
            robot = java_robot_tests(op)
        return jsonify({"unitTests": unit, "robotTests": robot})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# LLM provider helper
# ─────────────────────────────────────────────────────────────────────────────

#: Default model names per provider
_PROVIDER_DEFAULTS: dict[str, str] = {
    "ollama":  "llama3",
    "groq":    "llama-3.3-70b-versatile",
    "gemini":  "gemini-1.5-flash",
    "openai":  "gpt-4o",
}

#: OpenAI-compatible base URLs for each cloud provider
_PROVIDER_URLS: dict[str, str] = {
    "groq":   "https://api.groq.com/openai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
}


def _build_llm_client(provider: str, api_key: str, ollama_url: str = "http://localhost:11434"):
    """Return an OpenAI-compatible client for the requested provider.

    All four supported providers expose an OpenAI-compatible chat-completions
    API, so a single client type works for all of them.

    Args:
        provider:   One of 'ollama', 'groq', 'gemini', 'openai'.
        api_key:    API key (ignored / may be empty for Ollama).
        ollama_url: Base URL of the local Ollama server.

    Returns:
        (client, model_default) tuple.
    """
    try:
        from openai import OpenAI  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError("openai package not installed. Run: pip install openai") from exc

    provider = (provider or "ollama").lower().strip()
    model_default = _PROVIDER_DEFAULTS.get(provider, "llama3")

    if provider == "ollama":
        base = ollama_url.rstrip("/")
        return OpenAI(base_url=f"{base}/v1", api_key="ollama"), model_default

    if provider in _PROVIDER_URLS:
        if not api_key:
            raise ValueError(f"An API key is required for the {provider} provider.")
        return OpenAI(base_url=_PROVIDER_URLS[provider], api_key=api_key), model_default

    # openai (default)
    if not api_key:
        raise ValueError("An API key is required for the openai provider.")
    return OpenAI(api_key=api_key), model_default


@app.route("/api/ai-refine", methods=["POST"])
def api_ai_refine():
    body = request.get_json(force=True) or {}
    provider  = (body.get("provider")  or "ollama").lower().strip()
    api_key   = (body.get("apiKey")    or "").strip()
    model_req = (body.get("model")     or "").strip()
    ollama_url = (body.get("ollamaUrl") or "http://localhost:11434").strip()

    op_name      = body.get("operationName", "")
    history      = body.get("history", [])
    files        = body.get("files", {})
    lang         = body.get("language", "java")
    user_message = body.get("userMessage", "")

    try:
        client, model_default = _build_llm_client(provider, api_key, ollama_url)
    except (RuntimeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400

    model = model_req or model_default

    if lang == "java":
        system = (
            "You are an expert Java Spring Boot developer specialising in REST API services that "
            "wrap N-Central SOAP/WSDL operations. Help refine and improve generated Java code.\n\n"
            "Return improved files in Markdown fenced code blocks with these tags:\n"
            "```java:controller  ```java:service  ```java:serviceImpl\n"
            "```java:transformer  ```java:requestDto  ```java:responseDto\n"
            "```java:apiClient  ```javascript:jsClient\n\n"
            "Only include files that changed. Use plain text for explanations."
        )
        tag = "java"
    else:
        system = (
            "You are an expert Python / FastAPI developer specialising in REST API services that "
            "wrap N-Central SOAP/WSDL operations. Help refine and improve generated Python code.\n\n"
            "Return improved files in Markdown fenced code blocks with these tags:\n"
            "```python:controller  ```python:service  ```python:serviceImpl\n"
            "```python:transformer  ```python:requestDto  ```python:responseDto\n"
            "```python:apiClient  ```javascript:jsClient\n\n"
            "Only include files that changed. Use plain text for explanations."
        )
        tag = "python"

    code_ctx = "\n".join(f"```{tag}:{k}\n{v}\n```" for k, v in files.items())
    full_system = f'{system}\n\nCurrent files for operation "{op_name}":\n{code_ctx}'

    messages = [{"role": "system", "content": full_system}]
    for m in history:
        messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": user_message})

    try:
        completion = client.chat.completions.create(
            model=model, messages=messages, temperature=0.3
        )
        reply = completion.choices[0].message.content or ""
        updated = {}
        for m in re.finditer(rf"```({tag}|javascript):(\w+)\n([\s\S]*?)```", reply):
            updated[m.group(2)] = m.group(3).rstrip()
        return jsonify({"message": reply, "updatedFiles": updated or None})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 500


@app.route("/api/ai-tests", methods=["POST"])
def api_ai_tests():
    body = request.get_json(force=True) or {}
    provider   = (body.get("provider")   or "ollama").lower().strip()
    api_key    = (body.get("apiKey")     or "").strip()
    model_req  = (body.get("model")      or "").strip()
    ollama_url = (body.get("ollamaUrl")  or "http://localhost:11434").strip()

    op_name = body.get("operationName", "")
    files   = body.get("files", {})
    lang    = body.get("language", "java")
    tag     = "java" if lang == "java" else "python"
    framework      = "JUnit 5 / Mockito" if lang == "java" else "pytest + unittest.mock"
    framework_name = "Spring Boot"       if lang == "java" else "FastAPI"

    try:
        client, model_default = _build_llm_client(provider, api_key, ollama_url)
    except (RuntimeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400

    model = model_req or model_default

    code_ctx = "\n".join(f"### {k}\n```{tag}\n{v}\n```" for k, v in files.items())
    prompt = (
        f"Generate comprehensive unit tests and Robot Framework acceptance tests "
        f"for the {op_name} {framework_name} REST API.\n\n"
        f"{code_ctx}\n\n"
        f"Return:\n"
        f"1. {framework} unit tests in a ```{tag}:unitTests block\n"
        f"2. Robot Framework tests in a ```robot:robotTests block\n"
    )

    try:
        completion = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        reply = completion.choices[0].message.content or ""
        unit_m  = re.search(rf"```{tag}:unitTests\n([\s\S]*?)```", reply)
        robot_m = re.search(r"```robot:robotTests\n([\s\S]*?)```", reply)
        return jsonify({
            "unitTests":  unit_m.group(1).rstrip()  if unit_m  else "",
            "robotTests": robot_m.group(1).rstrip() if robot_m else "",
        })
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    print(f"\n  N-Central API Code Generator")
    print(f"  ► Open http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=debug)
