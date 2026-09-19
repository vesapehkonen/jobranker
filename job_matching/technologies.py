from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from .text import target_job_text


# Canonical name -> spelling variants. Keep this list explicit and reviewable.
# Ambiguous one-letter names and ordinary words such as Go are deliberately
# limited to variants that identify a programming language.
TECHNOLOGY_ALIASES: dict[str, tuple[str, ...]] = {
    # Languages and runtimes
    "Python": ("Python",), "Java": ("Java",),
    "JavaScript": ("JavaScript", "ECMAScript"), "TypeScript": ("TypeScript",),
    "C++": ("C++", "C plus plus"), "C": ("C language", "C programming", "C/C++", "C"),
    "C#": ("C#", "C sharp"), "Go": ("Golang", "Go language", "Go programming", "Go"),
    "Rust": ("Rust",), "Ruby": ("Ruby",), "PHP": ("PHP",), "Kotlin": ("Kotlin",),
    "Swift": ("Swift",), "Scala": ("Scala",), "R": ("R language", "R programming"),
    "Bash": ("Bash", "shell scripting"), "PowerShell": ("PowerShell",),
    ".NET": (".NET", "dotnet"), "Node.js": ("Node.js", "NodeJS", "Node JS"),
    # Backend, web, and mobile
    "FastAPI": ("FastAPI",), "Flask": ("Flask",), "Django": ("Django",),
    "Spring": ("Spring Framework", "Spring Boot", "Spring MVC"),
    "Express.js": ("Express.js", "ExpressJS"), "NestJS": ("NestJS",),
    "Ruby on Rails": ("Ruby on Rails", "Rails"), "ASP.NET": ("ASP.NET",),
    "React": ("React", "React.js", "ReactJS"), "Angular": ("Angular",),
    "Vue.js": ("Vue.js", "VueJS"), "Next.js": ("Next.js", "NextJS"),
    "Android": ("Android",), "Android SDK": ("Android SDK",),
    "Jetpack Compose": ("Jetpack Compose",), "iOS": ("iOS",),
    "React Native": ("React Native",), "Flutter": ("Flutter",),
    # APIs and data formats
    "REST": ("REST API", "REST APIs", "RESTful", "REST"), "GraphQL": ("GraphQL",),
    "gRPC": ("gRPC",), "WebSocket": ("WebSocket", "WebSockets"),
    "OpenAPI": ("OpenAPI", "Swagger"), "JSON": ("JSON",), "XML": ("XML",),
    # Databases, search, and messaging
    "SQL": ("SQL",), "PostgreSQL": ("PostgreSQL", "Postgres"),
    "MySQL": ("MySQL",), "MariaDB": ("MariaDB",), "SQLite": ("SQLite",),
    "SQL Server": ("SQL Server", "MSSQL"), "Oracle Database": ("Oracle Database", "Oracle DB"),
    "MongoDB": ("MongoDB",), "DynamoDB": ("DynamoDB",), "Cassandra": ("Cassandra",),
    "Redis": ("Redis",), "Elasticsearch": ("Elasticsearch", "Elastic Search"),
    "OpenSearch": ("OpenSearch",), "Solr": ("Solr",),
    "Kafka": ("Kafka", "Apache Kafka"), "RabbitMQ": ("RabbitMQ",),
    "SQS": ("Amazon SQS", "AWS SQS", "SQS"), "ActiveMQ": ("ActiveMQ",),
    # Cloud
    "AWS": ("AWS", "Amazon Web Services"), "Azure": ("Microsoft Azure", "Azure"),
    "GCP": ("GCP", "Google Cloud Platform", "Google Cloud"),
    "EC2": ("Amazon EC2", "AWS EC2", "EC2"), "S3": ("Amazon S3", "AWS S3", "S3"),
    "Lambda": ("AWS Lambda", "Amazon Lambda", "Lambda"), "ECS": ("Amazon ECS", "AWS ECS", "ECS"),
    "EKS": ("Amazon EKS", "AWS EKS", "EKS"), "RDS": ("Amazon RDS", "AWS RDS", "RDS"),
    "Aurora": ("Amazon Aurora", "AWS Aurora", "RDS Aurora", "Aurora"),
    "CloudFormation": ("CloudFormation",), "CloudWatch": ("CloudWatch",),
    "Azure Functions": ("Azure Functions",), "Azure DevOps": ("Azure DevOps",),
    "BigQuery": ("BigQuery",), "Cloud Run": ("Cloud Run",),
    "Google Kubernetes Engine": ("Google Kubernetes Engine", "Kubernetes Engine", "GKE"),
    # Infrastructure and delivery
    "Docker": ("Docker",), "Kubernetes": ("Kubernetes", "K8s"),
    "Terraform": ("Terraform",), "Ansible": ("Ansible",), "Pulumi": ("Pulumi",),
    "Helm": ("Helm",), "OpenShift": ("OpenShift",), "Vagrant": ("Vagrant",),
    "VMware": ("VMware",), "Hyper-V": ("Hyper-V",),
    "Jenkins": ("Jenkins",), "GitHub Actions": ("GitHub Actions",),
    "GitLab CI": ("GitLab CI", "GitLab CI/CD"), "CircleCI": ("CircleCI",),
    "TeamCity": ("TeamCity",), "Argo CD": ("Argo CD", "ArgoCD"),
    "Git": ("Git",), "GitHub": ("GitHub",), "GitLab": ("GitLab",),
    # Data, ML, and observability
    "Spark": ("Apache Spark", "PySpark", "Spark"), "Hadoop": ("Hadoop",),
    "Airflow": ("Apache Airflow", "Airflow"), "dbt": ("dbt",),
    "Pandas": ("Pandas",), "NumPy": ("NumPy",), "scikit-learn": ("scikit-learn", "sklearn"),
    "TensorFlow": ("TensorFlow",), "PyTorch": ("PyTorch",),
    "Hugging Face": ("Hugging Face", "HuggingFace"), "LangChain": ("LangChain",),
    "OpenAI API": ("OpenAI API",), "MLflow": ("MLflow",),
    "Prometheus": ("Prometheus",), "Grafana": ("Grafana",),
    "Datadog": ("Datadog",), "Splunk": ("Splunk",),
    "OpenTelemetry": ("OpenTelemetry",), "New Relic": ("New Relic",),
    # Testing, build, and operating systems
    "pytest": ("pytest",), "JUnit": ("JUnit",), "Selenium": ("Selenium",),
    "Playwright": ("Playwright",), "Cypress": ("Cypress",),
    "CMake": ("CMake",), "Maven": ("Maven",), "Gradle": ("Gradle",),
    "Linux": ("Linux",), "Windows": ("Windows",), "macOS": ("macOS", "Mac OS"),
    "Yocto": ("Yocto",), "Jira": ("Jira",), "ServiceNow": ("ServiceNow",),

    # Additional languages, runtimes, and developer platforms
    "Elixir": ("Elixir",), "Erlang": ("Erlang",), "Clojure": ("Clojure",),
    "F#": ("F#", "F sharp"), "VB.NET": ("VB.NET", "Visual Basic .NET"),
    "Visual Basic": ("Visual Basic", "VB6", "VB"), "Perl": ("Perl",), "Lua": ("Lua",),
    "Dart": ("Dart",), "Groovy": ("Groovy",), "Haskell": ("Haskell",),
    "Julia": ("Julia language", "Julia programming"), "MATLAB": ("MATLAB",),
    "Objective-C": ("Objective-C", "Objective C"), "COBOL": ("COBOL",),
    "Fortran": ("Fortran",), "Assembly": ("assembly language", "assembly programming"),
    "Solidity": ("Solidity",), "VHDL": ("VHDL",), "Verilog": ("Verilog",),
    "SystemVerilog": ("SystemVerilog", "System Verilog"),
    "Delphi": ("Delphi", "Object Pascal"), "Tcl": ("Tcl",),
    "CUDA": ("CUDA",), "OpenCL": ("OpenCL",), "WebAssembly": ("WebAssembly", "Wasm"),
    "AVX-512": ("AVX-512", "AVX512"),
    "Deno": ("Deno",), "Bun": ("Bun runtime", "Bun.js"),

    # Web, application, and mobile frameworks
    "Svelte": ("Svelte",), "SvelteKit": ("SvelteKit",), "Nuxt": ("Nuxt", "Nuxt.js"),
    "Remix": ("Remix framework", "Remix.run"), "Astro": ("Astro framework", "Astro.js"),
    "HTMX": ("HTMX",), "jQuery": ("jQuery",), "Bootstrap": ("Bootstrap CSS", "Twitter Bootstrap"),
    "Tailwind CSS": ("Tailwind CSS", "TailwindCSS"), "Material UI": ("Material UI", "Material-UI", "MUI"),
    "Redux": ("Redux",), "MobX": ("MobX",), "RxJS": ("RxJS",),
    "Electron": ("Electron.js", "Electron framework"), "Tauri": ("Tauri",),
    "Laravel": ("Laravel",), "Symfony": ("Symfony",), "CodeIgniter": ("CodeIgniter",),
    "Phoenix": ("Phoenix Framework",), "Play Framework": ("Play Framework",),
    "Quarkus": ("Quarkus",), "Micronaut": ("Micronaut",), "Vert.x": ("Vert.x", "Vertx"),
    "Jakarta EE": ("Jakarta EE", "Java EE", "J2EE"), "Hibernate": ("Hibernate ORM", "Hibernate"),
    "Struts": ("Apache Struts", "Struts"), "Grails": ("Grails",),
    "Blazor": ("Blazor",), "MAUI": (".NET MAUI", "MAUI"), "WPF": ("WPF", "Windows Presentation Foundation"),
    "WinForms": ("WinForms", "Windows Forms"), "Unity": ("Unity Engine", "Unity3D"),
    "Unreal Engine": ("Unreal Engine", "UE4", "UE5"),
    "Xamarin": ("Xamarin",), "Ionic": ("Ionic Framework", "Ionic"),
    "Cordova": ("Apache Cordova", "Cordova"), "Capacitor": ("Capacitor.js", "Ionic Capacitor"),

    # API, integration, identity, and protocols
    "SOAP": ("SOAP API", "SOAP web service", "SOAP services", "SOAP"), "OAuth": ("OAuth", "OAuth2", "OAuth 2.0"),
    "OpenID Connect": ("OpenID Connect", "OIDC"), "SAML": ("SAML", "SAML 2.0"),
    "JWT": ("JWT", "JSON Web Token", "JSON Web Tokens"), "Protobuf": ("Protocol Buffers", "Protobuf"),
    "Avro": ("Apache Avro", "Avro"), "Thrift": ("Apache Thrift",),
    "MQTT": ("MQTT",), "AMQP": ("AMQP",), "EDI": ("Electronic Data Interchange", "EDI"),
    "OData": ("OData",), "WebRTC": ("WebRTC",), "Nginx": ("Nginx",),
    "Apache HTTP Server": ("Apache HTTP Server", "Apache Web Server", "httpd"),
    "IIS": ("Microsoft IIS", "Internet Information Services", "IIS"),

    # Databases, warehouses, caches, search, and streaming
    "Oracle": ("Oracle Database", "Oracle RDBMS", "Oracle"), "DB2": ("IBM DB2", "Db2"),
    "CockroachDB": ("CockroachDB",), "Snowflake": ("Snowflake", "Snowflake Data Cloud"),
    "Redshift": ("Amazon Redshift", "AWS Redshift", "Redshift"), "Databricks": ("Databricks",),
    "ClickHouse": ("ClickHouse",), "TimescaleDB": ("TimescaleDB",),
    "InfluxDB": ("InfluxDB",), "Neo4j": ("Neo4j",), "Couchbase": ("Couchbase",),
    "CouchDB": ("Apache CouchDB", "CouchDB"), "Firestore": ("Cloud Firestore", "Firestore"),
    "Firebase Realtime Database": ("Firebase Realtime Database",),
    "Cosmos DB": ("Azure Cosmos DB", "Cosmos DB", "CosmosDB"),
    "Teradata": ("Teradata",), "Vertica": ("Vertica",), "Trino": ("Trino",),
    "Presto": ("PrestoDB", "Presto SQL", "Presto"), "Hive": ("Apache Hive", "Hive"), "HBase": ("Apache HBase", "HBase"),
    "Memcached": ("Memcached",), "NATS": ("NATS.io", "NATS messaging"),
    "Pulsar": ("Apache Pulsar",), "Kinesis": ("Amazon Kinesis", "AWS Kinesis"),
    "EventBridge": ("Amazon EventBridge", "AWS EventBridge"), "SNS": ("Amazon SNS", "AWS SNS", "SNS"),
    "MSMQ": ("Microsoft Message Queuing", "MSMQ"),

    # AWS services
    "API Gateway": ("Amazon API Gateway", "AWS API Gateway"),
    "Fargate": ("AWS Fargate", "Amazon Fargate"), "Step Functions": ("AWS Step Functions", "Step Functions"),
    "DMS": ("AWS DMS", "Amazon Database Migration Service"), "Glue": ("AWS Glue", "Glue"),
    "Athena": ("Amazon Athena", "AWS Athena"), "EMR": ("Amazon EMR", "AWS EMR", "EMR"),
    "SageMaker": ("Amazon SageMaker", "AWS SageMaker", "SageMaker"), "Bedrock": ("Amazon Bedrock", "AWS Bedrock", "Bedrock"),
    "Cognito": ("Amazon Cognito", "AWS Cognito"), "Route 53": ("Amazon Route 53", "AWS Route 53", "Route53"),
    "VPC": ("Amazon VPC", "AWS VPC", "VPC"), "IAM": ("AWS IAM", "Amazon IAM"),
    "Secrets Manager": ("AWS Secrets Manager",), "KMS": ("AWS KMS", "Amazon KMS"),
    "CodePipeline": ("AWS CodePipeline",), "CodeBuild": ("AWS CodeBuild",),

    # Azure and Google Cloud services
    "AKS": ("Azure Kubernetes Service", "AKS"), "Azure SQL": ("Azure SQL",),
    "Azure Storage": ("Azure Storage", "Azure Blob Storage"), "Azure Service Bus": ("Azure Service Bus", "Service Bus"),
    "Azure Key Vault": ("Azure Key Vault",), "Azure Data Factory": ("Azure Data Factory", "ADF"),
    "Azure Synapse": ("Azure Synapse", "Synapse Analytics"), "Azure App Service": ("Azure App Service",),
    "Azure Container Apps": ("Azure Container Apps",), "Azure Monitor": ("Azure Monitor",),
    "Vertex AI": ("Vertex AI",), "Pub/Sub": ("Google Cloud Pub/Sub", "Google Pub/Sub"),
    "Cloud Functions": ("Google Cloud Functions", "GCP Cloud Functions", "Cloud Functions"),
    "Cloud Storage": ("Google Cloud Storage", "GCS bucket", "GCS buckets", "Cloud Storage"),
    "Cloud SQL": ("Google Cloud SQL", "GCP Cloud SQL", "Cloud SQL"), "Spanner": ("Google Cloud Spanner", "Cloud Spanner"),
    "Dataflow": ("Google Cloud Dataflow", "GCP Dataflow"), "Dataproc": ("Google Cloud Dataproc", "GCP Dataproc"),

    # Containers, infrastructure, networking, and platform engineering
    "Podman": ("Podman",), "containerd": ("containerd",), "Nomad": ("HashiCorp Nomad", "Nomad"),
    "Consul": ("HashiCorp Consul", "Consul"), "Vault": ("HashiCorp Vault",),
    "Packer": ("HashiCorp Packer", "Packer"), "Chef": ("Chef Infra", "Chef configuration management", "Chef"),
    "Puppet": ("Puppet",), "SaltStack": ("SaltStack", "Salt Project"),
    "Istio": ("Istio",), "Linkerd": ("Linkerd",), "Envoy": ("Envoy Proxy",),
    "Traefik": ("Traefik",), "HAProxy": ("HAProxy",), "Cilium": ("Cilium",),
    "Calico": ("Project Calico", "Calico networking"), "Kustomize": ("Kustomize",),
    "Flux CD": ("Flux CD", "FluxCD", "Flux"), "Spinnaker": ("Spinnaker",),
    "Tekton": ("Tekton",), "Bamboo": ("Atlassian Bamboo", "Bamboo CI"),
    "Octopus Deploy": ("Octopus Deploy", "Octopus"), "Artifactory": ("JFrog Artifactory", "Artifactory"),
    "Nexus Repository": ("Sonatype Nexus", "Nexus Repository"),
    "Cloudflare": ("Cloudflare",), "Akamai": ("Akamai",),
    "Cisco IOS": ("Cisco IOS",), "Juniper Junos": ("Junos OS", "Juniper Junos"),

    # Data engineering, analytics, ML, and AI
    "Flink": ("Apache Flink", "Flink"), "Beam": ("Apache Beam",), "NiFi": ("Apache NiFi", "NiFi"),
    "Dagster": ("Dagster",), "Prefect": ("Prefect",), "Luigi": ("Luigi workflow",),
    "Dask": ("Dask",), "Polars": ("Polars",), "SciPy": ("SciPy",),
    "Matplotlib": ("Matplotlib",), "Seaborn": ("Seaborn",), "Jupyter": ("Jupyter", "JupyterLab", "Jupyter Notebook"),
    "Keras": ("Keras",), "XGBoost": ("XGBoost",), "LightGBM": ("LightGBM",),
    "CatBoost": ("CatBoost",), "ONNX": ("ONNX",), "OpenCV": ("OpenCV",),
    "spaCy": ("spaCy",), "NLTK": ("NLTK",), "Transformers": ("Hugging Face Transformers", "Transformers"),
    "Sentence Transformers": ("Sentence Transformers", "sentence-transformers"),
    "LlamaIndex": ("LlamaIndex",), "Ollama": ("Ollama",), "vLLM": ("vLLM",),
    "Ray": ("Ray framework", "Ray Serve"), "Kubeflow": ("Kubeflow",),
    "Weights & Biases": ("Weights & Biases", "Weights and Biases", "wandb"),
    "Tableau": ("Tableau",), "Power BI": ("Power BI", "PowerBI"), "Looker": ("Looker",),
    "Qlik": ("Qlik Sense", "QlikView"), "Alteryx": ("Alteryx",),

    # Monitoring, logging, tracing, and incident tooling
    "Elastic Stack": ("Elastic Stack", "ELK Stack", "ELK"), "Kibana": ("Kibana",),
    "Logstash": ("Logstash",), "Loki": ("Grafana Loki", "Loki logging"),
    "Jaeger": ("Jaeger tracing", "Jaeger"), "Zipkin": ("Zipkin",),
    "Sentry": ("Sentry",), "PagerDuty": ("PagerDuty",), "Opsgenie": ("Opsgenie",),
    "Dynatrace": ("Dynatrace",), "AppDynamics": ("AppDynamics",), "Nagios": ("Nagios",),
    "Zabbix": ("Zabbix",), "SolarWinds": ("SolarWinds",),

    # Testing, build, package, source-control, and developer tooling
    "NUnit": ("NUnit",), "xUnit": ("xUnit.net", "xUnit"), "MSTest": ("MSTest",),
    "Jest": ("Jest testing", "Jest.js"), "Mocha": ("Mocha.js", "Mocha testing"),
    "Vitest": ("Vitest",), "TestNG": ("TestNG",), "Cucumber": ("Cucumber testing", "Cucumber BDD"),
    "Robot Framework": ("Robot Framework",), "Postman": ("Postman",), "SoapUI": ("SoapUI",),
    "JMeter": ("Apache JMeter", "JMeter"), "Gatling": ("Gatling load testing",),
    "k6": ("Grafana k6", "k6 load testing", "k6"), "SonarQube": ("SonarQube",),
    "Snyk": ("Snyk",), "Checkmarx": ("Checkmarx",), "Veracode": ("Veracode",),
    "Gradle": ("Gradle",), "Ant": ("Apache Ant",), "Bazel": ("Bazel",),
    "Meson": ("Meson build system",), "Ninja": ("Ninja build", "Ninja build system"),
    "npm": ("npm",), "Yarn": ("Yarn package manager",), "pnpm": ("pnpm",),
    "pip": ("pip package manager", "Python pip"), "Poetry": ("Python Poetry", "Poetry package manager"),
    "uv": ("uv Python package manager", "Astral uv"), "Conda": ("Conda", "Anaconda package manager"),
    "NuGet": ("NuGet",), "Maven": ("Maven",), "Gradle": ("Gradle",),
    "Subversion": ("Subversion", "SVN"), "Mercurial": ("Mercurial SCM",),
    "Perforce": ("Perforce", "Helix Core"), "Bitbucket": ("Bitbucket",),

    # Security, identity, SIEM, and vulnerability tooling
    "Okta": ("Okta",), "Auth0": ("Auth0",), "Keycloak": ("Keycloak",),
    "Microsoft Entra ID": ("Microsoft Entra ID", "Azure Active Directory", "Azure AD"),
    "Active Directory": ("Active Directory", "Microsoft AD"), "LDAP": ("LDAP",),
    "CrowdStrike": ("CrowdStrike",), "SentinelOne": ("SentinelOne",),
    "Microsoft Sentinel": ("Microsoft Sentinel", "Azure Sentinel"),
    "QRadar": ("IBM QRadar", "QRadar"), "Nessus": ("Nessus",),
    "Qualys": ("Qualys",), "Burp Suite": ("Burp Suite",), "Metasploit": ("Metasploit",),
    "Wireshark": ("Wireshark",), "Nmap": ("Nmap",), "Snort": ("Snort IDS", "Snort"),
    "Suricata": ("Suricata IDS", "Suricata"), "HashiCorp Vault": ("HashiCorp Vault",),

    # Embedded systems, electronics, robotics, and industrial automation
    "RTOS": ("RTOS", "real-time operating system", "real time operating system"),
    "FreeRTOS": ("FreeRTOS",), "Zephyr": ("Zephyr RTOS", "Zephyr Project"),
    "VxWorks": ("VxWorks",), "QNX": ("QNX",), "Embedded Linux": ("Embedded Linux",),
    "microcontroller": ("microcontroller", "microcontrollers", "MCU", "MCUs"),
    "microprocessor": ("microprocessor", "microprocessors", "MPU", "MPUs"),
    "FPGA": ("FPGA", "FPGAs"), "SoC": ("system-on-chip", "system on chip", "SoC"),
    "ARM": ("ARM Cortex", "ARM processor", "ARM microcontroller"), "RISC-V": ("RISC-V", "RISC V"),
    "STM32": ("STM32",), "ESP32": ("ESP32",), "Arduino": ("Arduino",),
    "Raspberry Pi": ("Raspberry Pi",), "JTAG": ("JTAG",),
    "I2C": ("I2C", "I²C"), "SPI": ("SPI bus", "SPI interface"), "UART": ("UART",),
    "CAN bus": ("CAN bus", "CANbus", "CAN protocol", "CAN interface"), "Modbus": ("Modbus",), "EtherCAT": ("EtherCAT",),
    "PROFINET": ("PROFINET",), "PROFIBUS": ("PROFIBUS",), "OPC UA": ("OPC UA", "OPC-UA"),
    "PLC": ("PLC programming", "programmable logic controller", "programmable logic controllers"),
    "SCADA": ("SCADA",), "HMI": ("HMI programming", "human-machine interface", "human machine interface"),
    "Siemens TIA Portal": ("TIA Portal", "Siemens TIA Portal"),
    "Allen-Bradley": ("Allen-Bradley", "Allen Bradley", "Rockwell Automation"),
    "LabVIEW": ("LabVIEW",), "ROS": ("Robot Operating System", "ROS2", "ROS 2"),
    "MATLAB/Simulink": ("Simulink", "MATLAB/Simulink"),

    # CAD, CAM, CNC, CMM, mechanical, and manufacturing software
    "CNC": ("CNC", "computer numerical control"),
    "G-code": ("G-code", "G code", "Gcode"), "CAD": ("CAD software", "computer-aided design", "computer aided design"),
    "CAM": ("CAM software", "computer-aided manufacturing", "computer aided manufacturing"),
    "CAD/CAM": ("CAD/CAM", "CAD CAM"), "CMM": ("CMM programming", "coordinate measuring machine", "coordinate measuring machines"),
    "Mastercam": ("Mastercam", "MasterCAM", "Master Cam"), "CATIA": ("CATIA", "CATIA V5", "CATIA V6"),
    "Vericut": ("VERICUT", "Vericut"), "SigmaNEST": ("SigmaNEST", "Sigma Nest"),
    "PC-DMIS": ("PC-DMIS", "PC DMIS", "PCDMIS"), "MODUS": ("Renishaw MODUS", "MODUS CMM"),
    "CAMIO": ("CAMIO", "Nikon CAMIO"), "CALYPSO": ("ZEISS CALYPSO", "Calypso CMM"),
    "AutoCAD": ("AutoCAD",), "SolidWorks": ("SolidWorks", "SOLIDWORKS"),
    "Autodesk Inventor": ("Autodesk Inventor",), "Fusion 360": ("Autodesk Fusion 360", "Fusion 360"),
    "Creo": ("PTC Creo", "Creo Parametric"), "NX": ("Siemens NX", "NX CAD", "NX CAM"),
    "Solid Edge": ("Solid Edge",), "Revit": ("Autodesk Revit", "Revit"),
    "Civil 3D": ("AutoCAD Civil 3D", "Civil 3D"), "MicroStation": ("Bentley MicroStation", "MicroStation"),
    "ANSYS": ("ANSYS", "Ansys Mechanical"), "Abaqus": ("Abaqus", "SIMULIA Abaqus"),
    "HyperMesh": ("Altair HyperMesh", "HyperMesh"), "PowerMill": ("Autodesk PowerMill", "PowerMill"),
    "GibbsCAM": ("GibbsCAM", "Gibbs CAM"), "Edgecam": ("Edgecam",), "Esprit CAM": ("ESPRIT CAM", "Esprit CAM"),

    # Electronic design automation and semiconductor tooling
    "Altium Designer": ("Altium Designer", "Altium"), "KiCad": ("KiCad",),
    "OrCAD": ("OrCAD",), "Cadence Allegro": ("Cadence Allegro", "Allegro PCB"),
    "Cadence Virtuoso": ("Cadence Virtuoso", "Virtuoso IC"), "Mentor Graphics": ("Mentor Graphics", "Siemens EDA"),
    "Xilinx Vivado": ("Xilinx Vivado", "AMD Vivado", "Vivado"),
    "Quartus": ("Intel Quartus", "Altera Quartus", "Quartus Prime"),
    "LTspice": ("LTspice",), "PSpice": ("PSpice",),

    # Enterprise, CRM, ERP, ITSM, and business platforms
    "Salesforce": ("Salesforce", "Salesforce CRM"), "SAP": ("SAP ERP", "SAP S/4HANA", "S/4HANA"),
    "SAP ABAP": ("ABAP", "SAP ABAP"), "SAP HANA": ("SAP HANA", "HANA database"),
    "Oracle E-Business Suite": ("Oracle E-Business Suite", "Oracle EBS"),
    "Oracle PeopleSoft": ("PeopleSoft", "Oracle PeopleSoft"), "Workday": ("Workday",),
    "Microsoft Dynamics 365": ("Microsoft Dynamics 365", "Dynamics 365"),
    "NetSuite": ("Oracle NetSuite", "NetSuite"), "Epicor": ("Epicor ERP", "Epicor"),
    "Infor": ("Infor ERP", "Infor CloudSuite"), "ServiceNow": ("ServiceNow",),
    "SharePoint": ("Microsoft SharePoint", "SharePoint"), "Power Apps": ("Microsoft Power Apps", "Power Apps"),
    "Power Automate": ("Microsoft Power Automate", "Power Automate"),
    "UiPath": ("UiPath",), "Automation Anywhere": ("Automation Anywhere",), "Blue Prism": ("Blue Prism",),

    # Collaboration, project, design, and productivity tools
    "Confluence": ("Atlassian Confluence", "Confluence"), "Trello": ("Trello",),
    "Asana": ("Asana",), "Monday.com": ("Monday.com",), "Smartsheet": ("Smartsheet",),
    "Azure Boards": ("Azure Boards",), "Figma": ("Figma",), "Sketch": ("Sketch design tool",),
    "Adobe XD": ("Adobe XD",), "Photoshop": ("Adobe Photoshop", "Photoshop"),
    "Illustrator": ("Adobe Illustrator", "Illustrator"),

    # Virtualization, storage, backup, and systems administration
    "Proxmox": ("Proxmox", "Proxmox VE"), "Citrix": ("Citrix Virtual Apps", "Citrix Virtual Desktops", "Citrix XenApp", "Citrix XenDesktop"),
    "KVM": ("KVM virtualization", "Kernel-based Virtual Machine"), "VirtualBox": ("Oracle VirtualBox", "VirtualBox"),
    "Veeam": ("Veeam",), "Commvault": ("Commvault",), "NetApp": ("NetApp ONTAP", "NetApp storage"),
    "Dell EMC": ("Dell EMC", "EMC storage"), "Ceph": ("Ceph",), "GlusterFS": ("GlusterFS",),
    "ZFS": ("ZFS",), "NFS": ("Network File System", "NFS"), "SMB": ("SMB protocol", "Server Message Block"),

    # Concrete technologies verified in stored cleaned job descriptions
    "NoSQL": ("NoSQL",), "LLM": ("LLM", "LLMs", "Large Language Model", "Large Language Models"),
    "RAG": ("RAG", "retrieval-augmented generation", "retrieval augmented generation"),
    "ElastiCache": ("Amazon ElastiCache", "AWS ElastiCache", "ElastiCache"),
    "Claude": ("Claude", "Claude Code", "Claude Opus"),
    "GitHub Copilot": ("GitHub Copilot", "Copilot", "Copilot Studio"),
    "Cursor": ("Cursor",), "Parquet": ("Apache Parquet", "Parquet"),
    "JAX": ("JAX",), "SGLang": ("SGLang",), "TensorRT": ("TensorRT",),
    "Torch XLA": ("TorchXLA", "Torch XLA"), "NCCL": ("NCCL",),
    "MPI": ("MPI", "Intel MPI", "MPICH"), "OpenMP": ("OpenMP",),
    "AWS CDK": ("AWS CDK", "Cloud Development Kit", "CDK"),
    "CDKTF": ("CDKTF", "Terraform CDK"), "Crossplane": ("Crossplane",),
    "HTML": ("HTML", "HTML5"), "CSS": ("CSS", "CSS3", "CSS 3.0"),
    "Apache Storm": ("Apache Storm",), "Apache Iceberg": ("Apache Iceberg", "Iceberg"),
    "Apache Pinot": ("Apache Pinot",), "Apache Arrow": ("Apache Arrow", "Arrow"),
    "CloudFront": ("Amazon CloudFront", "AWS CloudFront", "CloudFront"),
    "Amazon ECR": ("Amazon ECR", "AWS ECR"), "Amazon Connect": ("Amazon Connect",),
    "Amazon DocumentDB": ("Amazon DocumentDB", "AWS DocumentDB", "DocumentDB"),
    "AWS GovCloud": ("AWS GovCloud",), "AWS SDK": ("AWS SDK",),
    "AWS-LC": ("AWS-LC",), "MWAA": ("Amazon MWAA", "AWS MWAA", "MWAA"),
    "Azure AI Services": ("Azure Cognitive Services", "Azure AI Foundry"),
    "Azure CLI": ("Azure CLI",), "Azure Event Hubs": ("Azure Event Hubs", "Azure EventHub"),
    "Azure OpenAI": ("Azure OpenAI",), "Application Insights": ("Application Insights", "AppInsights"),
    "Microsoft Fabric": ("Microsoft Fabric",),
    "Microsoft Power Platform": ("Microsoft Power Platform", "Power Platform", "Dataverse"),
    "OCI": ("Oracle Cloud Infrastructure", "OCI"), "Alibaba Cloud": ("Alibaba Cloud", "Aliyun"),
    "Google App Engine": ("Google App Engine", "App Engine"),
    "Google Compute Engine": ("Google Compute Engine", "Compute Engine"),
    "Google Cloud Bigtable": ("Google Cloud Bigtable", "Cloud Bigtable", "BigTable"),
    "Google Cloud Armor": ("Google Cloud Armor", "Cloud Armor"),
    "Google Cloud Operations": ("Google Cloud Operations", "Cloud Logging", "Cloud Monitoring", "Cloud Trace"),
    "Persistent Disk": ("Google Persistent Disk", "Persistent Disk"),
    "Security Command Center": ("Google Security Command Center", "Security Command Center"),
    "Databricks Apps": ("Databricks Apps",), "Streamlit": ("Streamlit",),
    "Plotly Dash": ("Plotly Dash", "Dash"), "Gradio": ("Gradio",), "Shiny": ("Shiny",),
    "LangGraph": ("LangGraph",), "Semantic Kernel": ("Semantic Kernel",),
    "AutoGen": ("AutoGen",), "LangChain4j": ("LangChain4j",),
    "llama.cpp": ("llama.cpp",), "ggml": ("ggml",),
    "ONNX Runtime": ("ONNX Runtime",), "ExecuTorch": ("ExecuTorch",),
    "Triton Inference Server": ("Triton Inference Server",),
    "NVIDIA Neuron": ("AWS Neuron", "Neuron"), "NVIDIA RAPIDS": ("NVIDIA RAPIDS",),
    "TPU": ("TPU", "TPUs"), "cuDNN": ("cuDNN",),
    "Informatica": ("Informatica",), "SSIS": ("SSIS", "SQL Server Integration Services"),
    "Fivetran": ("Fivetran",), "HVR": ("HVR", "Fivetran HVR"),
    "Ctrl-M": ("Ctrl-M", "Control-M"), "Flyte": ("Flyte",),
    "Milvus": ("Milvus",), "Kafka Streams": ("Kafka Streams",),
    "Hive Metastore": ("Hive Metastore",), "KQL": ("KQL", "Kusto Query Language"),
    "PL/SQL": ("PL/SQL", "Oracle PL/SQL"), "T-SQL": ("T-SQL", "Transact-SQL"),
    "SAP Sybase": ("SAP Sybase ASE", "SAP Sybase IQ", "SAP Sybase Replication"),
    "Salesforce Commerce Cloud": ("Salesforce Commerce Cloud",),
    "MuleSoft": ("MuleSoft",), "Dapper": ("Dapper",),
    "Guava": ("Google Guava", "Guava"), "Kestrel": ("Kestrel",),
    "Tomcat": ("Apache Tomcat", "Tomcat"), "Spring AI": ("Spring AI",),
    "Jetpack": ("Android Jetpack", "Jetpack libraries", "Jetpack"),
    "MVVM": ("MVVM",), "Expo": ("Expo",), "Firebase": ("Firebase",),
    "Google Fit": ("Google Fit",), "Health Connect": ("Health Connect",),
    "Google Maps": ("Google Maps",), "Google Places API": ("Google Places API",),
    "RevenueCat": ("RevenueCat",), "Bluetooth": ("Bluetooth",),
    "SCIM": ("SCIM", "System for Cross-domain Identity Management"),
    "TCP/IP": ("TCP/IP",), "TCP": ("TCP protocol", "TCP networking"),
    "UDP": ("UDP",), "Ethernet": ("Ethernet",),
    "DNS": ("DNS",), "RDMA": ("RDMA",),
    "DPDK": ("DPDK",), "eBPF": ("eBPF",), "XDP": ("XDP", "AF_XDP"),
    "Vulkan": ("Vulkan",), "Metal": ("Apple Metal", "Metal API"),
    "OpenEmbedded": ("OpenEmbedded",), "PetaLinux": ("PetaLinux",),
    "Ubuntu": ("Ubuntu",), "RHEL": ("RHEL", "Red Hat Enterprise Linux", "Red Hat Linux"),
    "Ångström Linux": ("Ångström Linux", "Angstrom Linux"),
    "Unix": ("Unix",), "Cortex-M": ("Cortex-M",), "CPLD": ("CPLD",),
    "ADC": ("ADC",), "DAC": ("DAC",), "Xilinx Zynq": ("Xilinx Zynq", "Zynq"),
    "NXP i.MX": ("NXP i.MX",), "V4L2": ("V4L2",),
    "GCC": ("GCC",), "GDB": ("GDB",), "LLVM": ("LLVM",),
    "iptables": ("iptables",), "Linux perf": ("Linux perf",),
    "async-profiler": ("Async Profiler", "async-profiler"),
    "MSBuild": ("MSBuild",), "MSVC": ("MSVC",), "Kong": ("Kong Gateway", "Kong"),
    "Backstage": ("Backstage",), "Buildkite": ("Buildkite",), "KEDA": ("KEDA",),
    "Knative": ("Knative",), "etcd": ("etcd",), "Temporal": ("Temporal.io", "Temporal"),
    "Fastly": ("Fastly",), "WordPress": ("WordPress",),
    "YouTrack": ("YouTrack",), "Jira Service Management": ("Jira Service Management",),
    "Slack": ("Slack",), "Microsoft Teams": ("Microsoft Teams",),
    "JFrog Xray": ("JFrog Xray",),
    "Black Duck": ("Black Duck",), "LoadRunner": ("LoadRunner",),
    "PRTG": ("PRTG",), "Sumo Logic": ("Sumo Logic", "Sumo"), "SignalFx": ("SignalFx",),
    "Slurm": ("Slurm",), "SYCL": ("SYCL", "DPC++", "SYCL/DPC++"),
    "TBB": ("Intel TBB", "oneTBB", "TBB"), "YAML": ("YAML", "YML"),
    "XSD": ("XSD",), "XSLT": ("XSLT",), "MCP": ("Model Context Protocol", "MCP"),
    "McAfee DXL": ("McAfee DXL", "Data Exchange Layer", "DXL"),
    "LZ4": ("LZ4",), "Zstandard": ("Zstandard", "Zstd"),
}



@lru_cache(maxsize=None)
def _pattern(alias: str) -> re.Pattern[str]:
    return re.compile(r"(?<![A-Za-z0-9_])" + re.escape(alias) + r"(?![A-Za-z0-9_])", re.IGNORECASE)


def _context(text: str, start: int, end: int, radius: int = 120) -> str:
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    if line_end < 0:
        line_end = len(text)
    line = re.sub(r"\s+", " ", text[line_start:line_end].strip())
    if len(line) <= radius * 2:
        return line
    relative_start = start - line_start
    relative_end = end - line_start
    window_start = max(0, relative_start - radius)
    window_end = min(len(line), relative_end + radius)
    prefix = "…" if window_start else ""
    suffix = "…" if window_end < len(line) else ""
    return prefix + line[window_start:window_end].strip() + suffix


def _valid_match(
    canonical: str, alias: str, match: re.Match[str], text: str
) -> bool:
    matched = match.group(0)
    if alias in {"C", "Go", "VB"} and matched != alias:
        return False
    if alias == "C" and text[match.end():].startswith(("++", "#")):
        return False
    if alias == "REST" and matched != alias:
        return False
    if canonical in {"React", "SoC"} and alias == canonical and matched != alias:
        return False
    if canonical == "Git" and re.match(r"\s+hub\b", text[match.end():], re.I):
        return False

    context = text[max(0, match.start() - 100):min(len(text), match.end() + 100)]
    if canonical == "McAfee DXL" and alias == "DXL":
        return matched == "DXL" and bool(
            re.search(r"\b(?:McAfee|Data Exchange Layer)\b", context, re.I)
        )
    if alias in {"C", "Go", "VB"} and not re.search(
        r"\b(?:programming|language|code|Python|Java|JavaScript|TypeScript|Rust|Kotlin|Scala)\b|C\+\+|C#",
        context,
        re.I,
    ):
        return False
    if canonical == "Bedrock" and alias == "Bedrock" and not re.search(
        r"\b(?:AWS|Amazon|cloud|AI|ML|model)\b", context, re.I
    ):
        return False
    if canonical == "Aurora" and alias == "Aurora" and not re.search(
        r"\b(?:AWS|Amazon|RDS|database|SQL|cloud)\b", context, re.I
    ):
        return False
    if canonical == "Oracle" and alias == "Oracle":
        oracle_context = text[
            max(0, match.start() - 250):min(len(text), match.end() + 250)
        ]
        if re.search(
            r"\b(?:decentralized\s+)?oracle\s+(?:platform|network)s?\b|\bOracle Fusion\b",
            oracle_context,
            re.I,
        ):
            return False
        if not re.search(
            r"\b(?:database|SQL|data|technology|technologies)\b",
            oracle_context,
            re.I,
        ):
            return False
    if canonical == "Swift" and alias == "Swift":
        return bool(re.search(
            r"\b(?:programming|language|iOS|developer|engineer|software|code)\b",
            context,
            re.I,
        ))
    if canonical == "Kong" and alias == "Kong":
        return bool(re.search(r"\b(?:API|gateway|platform|ingress|service)\b", context, re.I))
    return True


def extract_technologies(text: str) -> list[dict[str, Any]]:
    text = target_job_text(text)
    found = []
    for canonical, aliases in TECHNOLOGY_ALIASES.items():
        matches: list[tuple[str, re.Match[str]]] = []
        for alias in aliases:
            matches.extend(
                (alias, match)
                for match in _pattern(alias).finditer(text)
                if _valid_match(canonical, alias, match, text)
            )
        if not matches:
            continue
        matches.sort(key=lambda item: (item[1].start(), -(item[1].end() - item[1].start())))
        distinct: list[tuple[str, re.Match[str]]] = []
        for candidate in matches:
            candidate_match = candidate[1]
            if any(
                candidate_match.start() < existing.end()
                and candidate_match.end() > existing.start()
                for _, existing in distinct
            ):
                continue
            distinct.append(candidate)
        matches = distinct
        found.append({
            "name": canonical,
            "aliases_found": list(dict.fromkeys(match.group(0) for _, match in matches)),
            "occurrences": len(matches),
            "contexts": list(dict.fromkeys(
                _context(text, match.start(), match.end()) for _, match in matches
            ))[:3],
        })
    names = {item["name"] for item in found}
    if "Hive Metastore" in names:
        found = [item for item in found if item["name"] != "Hive"]
    return sorted(found, key=lambda item: item["name"].lower())


def flatten_profile_text(profile: dict[str, Any]) -> str:
    parts: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            for item in value.values():
                visit(item)

    visit(profile)
    return "\n".join(parts)
