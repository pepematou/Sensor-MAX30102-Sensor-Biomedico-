# Monitor Biomédico MAX30102 para Raspberry Pi

Este proyecto permite leer un sensor biomédico **MAX30102** desde una Raspberry Pi y mostrar los datos en una interfaz gráfica hecha con **Tkinter**. La aplicación principal integra lectura del sensor, visualización en tiempo real, guardado local en CSV y envío de notificaciones por Telegram cuando se detectan valores críticos.

El sistema está pensado para una Raspberry Pi 5 con el sensor conectado por I2C. El código base proviene del repositorio `doug-burrell/max30102`, pero fue extendido con una aplicación gráfica completa.

## Origen del proyecto

La base de este proyecto viene de un repositorio de GitHub:

```text
https://github.com/doug-burrell/max30102
```

Ese repositorio proporciona el código principal para comunicarse con el sensor MAX30102 desde Raspberry Pi, leer datos por I2C y calcular BPM/SpO2.

Sobre esa base se agregaron las mejoras de este proyecto:

- Interfaz gráfica con Tkinter.
- Visualización de BPM, SpO2, temperatura y Raw IR.
- Guardado local en CSV.
- Alertas por Telegram.
- Envío manual de valores actuales.
- Generación y envío de reportes PDF con gráficas.
- Manejo de hilos para no congelar la interfaz.
- Tolerancia a fallos de red.

## Funciones principales

- Lectura en tiempo real del sensor MAX30102.
- Interfaz gráfica en tema oscuro.
- Visualización de:
  - BPM.
  - SpO2.
  - Temperatura.
  - Sensor IR en crudo.
- Botón para iniciar y detener el monitoreo.
- Guardado opcional en archivo CSV.
- Envío manual de valores actuales por Telegram.
- Generación de reporte PDF con tabla, resumen y gráficas.
- Envío del reporte PDF por Telegram.
- Prueba manual de alerta crítica.
- Alertas automáticas por Telegram cuando se superan umbrales médicos configurados.
- Hilos separados para evitar que la interfaz se congele.
- Manejo de errores de red para que una falla de Telegram no detenga el monitoreo local.

## Archivos importantes

- `app_medica_completa.py`
  Aplicación principal con GUI, control del sensor, CSV y Telegram.

- `../app_medica_completa.py`
  Lanzador desde la raíz del proyecto. Permite ejecutar la app con:

  ```bash
  python3 app_medica_completa.py
  ```

- `main.py`
  Script original de consola. Lee el sensor y muestra datos en terminal.

- `max30102.py`
  Driver de bajo nivel para el MAX30102. Configura registros I2C, lee FIFO y temperatura.

- `hrcalc.py`
  Algoritmo de cálculo de BPM y SpO2.

- `heartrate_monitor.py`
  Clase original para lectura del sensor en hilo.

- `registro_biomedico.csv`
  Archivo generado automáticamente si se activa el guardado desde la interfaz.

- `reporte_biomedico.pdf`
  Reporte generado desde la sesión actual cuando se presiona **Enviar reporte PDF**.

- `reporte_biomedico_graficas.png`
  Imagen temporal con las gráficas que se inserta dentro del PDF.

## Requisitos de hardware

- Raspberry Pi 5.
- Sensor MAX30102.
- I2C habilitado en la Raspberry Pi.
- Conexión a internet si se desea usar Telegram.

Conexión típica del sensor:

```text
MAX30102 VIN  -> Raspberry Pi 3.3V o 5V, según tu módulo
MAX30102 GND  -> Raspberry Pi GND
MAX30102 SDA  -> Raspberry Pi GPIO 2 / SDA
MAX30102 SCL  -> Raspberry Pi GPIO 3 / SCL
```

La dirección I2C usada por defecto es:

```text
0x57
```

## Habilitar I2C

En Raspberry Pi OS puedes habilitar I2C con:

```bash
sudo raspi-config
```

Luego entra en:

```text
Interface Options -> I2C -> Enable
```

Para comprobar que el sensor aparece:

```bash
i2cdetect -y 1
```

Deberías ver una dirección `57` en la tabla.

## Dependencias

Instala las dependencias principales:

```bash
sudo apt update
sudo apt install python3-tk python3-numpy python3-smbus i2c-tools
entorno/bin/python -m pip install requests matplotlib reportlab
```

En Raspberry Pi OS puede aparecer el error `externally-managed-environment` si intentas instalar paquetes globales con `python3 -m pip`. Por eso, en este proyecto se recomienda instalar las librerías de PDF y Telegram dentro del entorno virtual local `entorno/`.

La aplicación está preparada para ejecutarse con:

```bash
python3 app_medica_completa.py
```

y aun así buscar automáticamente `requests`, `matplotlib` y `reportlab` dentro de:

```text
entorno/lib/python3.13/site-packages
```

Esto permite usar el `python3` del sistema para acceder a `smbus` y al mismo tiempo usar las librerías instaladas en `entorno/`.

Si usas otro entorno virtual, asegúrate de que tenga disponibles:

```text
numpy
smbus
requests
tkinter
matplotlib
reportlab
```

`tkinter`, `numpy` y `smbus` suelen instalarse mejor desde `apt` en Raspberry Pi OS. `requests`, `matplotlib` y `reportlab` pueden instalarse en `entorno/` con `pip`.

Para verificar qué tiene instalado cada Python:

```bash
python3 -c "import smbus, numpy, tkinter; print('dependencias del sistema ok')"
entorno/bin/python -c "import requests, matplotlib, reportlab; print('dependencias del entorno ok')"
```

## Ejecutar la aplicación gráfica

Desde la raíz del proyecto:

```bash
cd ~/prueba_max30102
python3 app_medica_completa.py
```

También puedes ejecutarla directamente desde la carpeta del sensor:

```bash
cd ~/prueba_max30102/max30102
python3 app_medica_completa.py
```

## Ejecutar el script original de consola

El script original sigue disponible:

```bash
python3 max30102/main.py
```

Opciones:

```bash
python3 max30102/main.py --raw
python3 max30102/main.py --time 60
```

`--raw` imprime valores crudos IR y rojo.

`--time` define cuántos segundos durará la lectura.

## Interfaz gráfica

La aplicación muestra tres tarjetas principales:

- **Frecuencia Cardiaca**
  Muestra los BPM calculados.

- **Oxigenación**
  Muestra el SpO2 calculado.

- **Temperatura**
  Muestra la temperatura leída desde el sensor.

También muestra una etiqueta:

```text
Sensor IR (Raw)
```

Ese valor corresponde al último dato infrarrojo crudo obtenido desde el FIFO del MAX30102.

## Botones disponibles

### Iniciar monitoreo

Inicializa el sensor MAX30102 y empieza la lectura en un hilo secundario.

La interfaz no se congela porque Tkinter corre en el hilo principal y la lectura del hardware ocurre en otro hilo.

### Detener monitoreo

Detiene el hilo de lectura y apaga el sensor usando `sensor.shutdown()`.

### Guardar en registro_biomedico.csv

Activa o desactiva el guardado local.

Cuando está activado, cada lectura procesada se añade al archivo:

```text
registro_biomedico.csv
```

### Enviar valores actuales

Envía manualmente la última lectura real por Telegram.

El mensaje tiene este formato:

```text
Lectura actual del Monitor Biomédico MAX30102:
Fecha/Hora: 2026-05-28T...
BPM: ...
SpO2: ...%
Temperatura: ... °C
Sensor IR (Raw): ...
```

Este botón no usa cooldown porque es una acción manual del usuario.

Si aún no existe una lectura válida, la app mostrará:

```text
Aun no hay lecturas reales para enviar.
```

### Enviar reporte PDF

Genera un archivo:

```text
reporte_biomedico.pdf
```

El reporte incluye:

- Resumen de la sesión.
- Número total de lecturas.
- Conteo de eventos críticos.
- Promedio, mínimo y máximo de BPM.
- Promedio, mínimo y máximo de SpO2.
- Promedio, mínimo y máximo de temperatura.
- Promedio, mínimo y máximo de Raw IR.
- Gráfica de BPM en el tiempo.
- Gráfica de SpO2 en el tiempo.
- Gráfica de temperatura en el tiempo.
- Tabla con las últimas lecturas de la sesión.

Después de generarlo, la aplicación lo envía por Telegram como documento usando la API `sendDocument`.

Este proceso se ejecuta en un hilo separado para que la ventana no se congele.

### Probar alerta crítica

Simula una alerta con valores críticos:

```text
BPM: 130.0
SpO2: 89.0
Temperatura: 38.5 °C
```

Este botón sí usa el mismo sistema de cooldown que las alertas automáticas.

## Telegram

La aplicación usa la API de Telegram mediante la librería `requests`.

Los mensajes simples usan:

```text
sendMessage
```

Los reportes PDF usan:

```text
sendDocument
```

Debes configurar:

- `Telegram Token`
- `Chat ID`

Puedes escribirlos en los campos visibles de la interfaz.

También existen variables al inicio de `app_medica_completa.py`:

```python
DEFAULT_TELEGRAM_TOKEN = ""
DEFAULT_TELEGRAM_CHAT_ID = ""
```

Recomendación: no subas tokens reales a GitHub ni compartas capturas donde aparezcan. Si un token se filtra, revócalo desde BotFather y genera uno nuevo.

## Alertas automáticas

La app envía una alerta médica automática si detecta cualquiera de estas condiciones:

```text
SpO2 < 92
BPM > 120
BPM < 50
Temperatura > 38.0
```

Los umbrales se configuran al inicio de `app_medica_completa.py`:

```python
CRITICAL_SPO2_MIN = 92
CRITICAL_BPM_MAX = 120
CRITICAL_BPM_MIN = 50
CRITICAL_TEMP_MAX = 38.0
```

El mensaje automático tiene este formato:

```text
¡ALERTA MÉDICA! Paciente con parámetros críticos: 130.0 BPM, 89.0% SpO2 y 38.5 °C
```

## Cooldown de alertas

Para evitar saturar Telegram, el sistema usa un temporizador de cooldown.

Por defecto:

```python
ALERT_COOLDOWN_SECONDS = 120
```

Esto significa que, después de enviar una alerta crítica, la app esperará al menos 120 segundos antes de permitir otra alerta automática o prueba crítica.

El botón **Enviar valores actuales** no usa cooldown porque se considera envío manual.

## Archivo CSV

Si activas la casilla de guardado, la app escribe en:

```text
registro_biomedico.csv
```

El archivo contiene exactamente estas columnas:

```text
Fecha_Hora,BPM,SpO2,Temperatura,Raw_IR
```

Ejemplo:

```csv
Fecha_Hora,BPM,SpO2,Temperatura,Raw_IR
2026-05-28T06:40:15,72.50,97.20,31.06,98234
```

Si una lectura no está disponible, se guarda el campo vacío.

El CSV sigue siendo útil como registro liviano y editable. El PDF se genera desde las lecturas almacenadas en memoria durante la sesión actual.

## Reporte PDF

El botón **Enviar reporte PDF** crea un informe visual de la sesión actual.

Archivos generados:

```text
reporte_biomedico.pdf
reporte_biomedico_graficas.png
```

El PDF se genera con `reportlab` y las gráficas con `matplotlib`.

Si faltan esas dependencias, instala:

```bash
entorno/bin/python -m pip install matplotlib reportlab
```

Después puedes seguir ejecutando la app normalmente con:

```bash
python3 app_medica_completa.py
```

El reporte solo puede generarse si ya existe al menos una lectura en la sesión actual. Si acabas de abrir la app y todavía no has iniciado el monitoreo, la interfaz mostrará:

```text
Aun no hay lecturas para generar el PDF.
```

## Arquitectura del programa

La app está separada en clases:

### `Reading`

Modelo de datos para una lectura procesada.

Contiene:

- Fecha y hora.
- BPM.
- SpO2.
- Temperatura.
- Raw IR.
- Indicadores de validez.
- Detección de dedo.

### `SensorWorker`

Controla el sensor en un hilo secundario.

Responsabilidades:

- Inicializar `MAX30102`.
- Leer muestras desde FIFO.
- Extraer valores rojo e IR.
- Calcular BPM y SpO2 usando `hrcalc.py`.
- Leer temperatura con `sensor.read_temperature()`.
- Enviar lecturas procesadas a la interfaz mediante una cola.

### `AlertManager`

Gestiona los mensajes de Telegram.

Responsabilidades:

- Enviar mensajes manuales.
- Enviar documentos PDF.
- Detectar condiciones críticas.
- Aplicar cooldown.
- Ejecutar envíos de red en un hilo separado para no congelar la GUI.

### `MedicalMonitorApp`

Controla la interfaz Tkinter.

Responsabilidades:

- Construir la ventana.
- Actualizar tarjetas de BPM, SpO2 y temperatura.
- Mostrar Raw IR.
- Guardar CSV.
- Generar reportes PDF desde la sesión actual.
- Recibir datos del hilo del sensor.
- Lanzar envíos manuales o pruebas críticas.

## Tolerancia a fallos

El monitoreo local tiene prioridad.

Si Telegram falla por falta de Wi-Fi, token incorrecto, chat ID inválido o timeout, la app captura el error y lo muestra en la barra de estado.

El fallo de Telegram no debe detener:

- La GUI.
- El hilo del sensor.
- El guardado local.
- La lectura biomédica en pantalla.

## Temperatura

La temperatura se obtiene con:

```python
sensor.read_temperature()
```

Este método lee los registros internos del MAX30102:

- `REG_TEMP_INTR`
- `REG_TEMP_FRAC`
- `REG_TEMP_CONFIG`

Importante: esta temperatura corresponde a la temperatura interna del chip/sensor. No debe interpretarse automáticamente como temperatura corporal clínica sin calibración y validación.

## Notas sobre precisión

El MAX30102 es sensible a:

- Movimiento del dedo.
- Presión sobre el sensor.
- Luz ambiental.
- Mala colocación.
- Baja perfusión.
- Ruido eléctrico.

Para mejores lecturas:

- Mantén el dedo quieto.
- Evita presionar demasiado.
- Cubre el sensor de luz directa.
- Espera algunos segundos hasta que el cálculo se estabilice.

## Advertencia médica

Este proyecto es educativo y experimental.

No sustituye equipo médico certificado ni debe usarse como único sistema para tomar decisiones clínicas. Las alertas por Telegram son una ayuda tecnológica, no un sistema médico validado.

## Problemas comunes

### No abre la app desde la raíz

Usa:

```bash
python3 app_medica_completa.py
```

Si estás dentro de `max30102`, usa:

```bash
python3 app_medica_completa.py
```

### No se detecta el sensor

Verifica:

```bash
i2cdetect -y 1
```

Debe aparecer `57`.

### Error con `smbus`

Instala:

```bash
sudo apt install python3-smbus
```

### Error con `tkinter`

Instala:

```bash
sudo apt install python3-tk
```

### Telegram no manda mensajes

Revisa:

- Que la Raspberry tenga internet.
- Que `requests` esté instalado.
- Que `matplotlib` y `reportlab` estén instalados si quieres generar PDF.
- Que el Token sea correcto.
- Que el Chat ID sea correcto.
- Que el usuario haya iniciado conversación con el bot.

Instala `requests` si falta:

```bash
entorno/bin/python -m pip install requests
```

### No se genera el PDF

Revisa:

- Que ya exista al menos una lectura en la sesión actual.
- Que estén instalados `matplotlib` y `reportlab` en `entorno/`.
- Que tengas permisos de escritura en la carpeta desde donde ejecutaste la app.

Instala dependencias si falta alguna:

```bash
entorno/bin/python -m pip install matplotlib reportlab
```

Comprueba que el entorno virtual pueda importarlas:

```bash
entorno/bin/python -c "import matplotlib, reportlab; print('PDF ok')"
```

Comprueba también que el Python del sistema siga viendo el sensor:

```bash
python3 -c "import smbus; print('smbus ok')"
```

## Flujo recomendado de uso

1. Conecta el MAX30102 a la Raspberry Pi.
2. Verifica I2C con `i2cdetect -y 1`.
3. Ejecuta la aplicación:

   ```bash
   python3 app_medica_completa.py
   ```

4. Configura Token y Chat ID si usarás Telegram.
5. Presiona **Iniciar monitoreo**.
6. Espera a que aparezcan lecturas estables.
7. Activa el guardado CSV si necesitas registro local.
8. Usa **Enviar valores actuales** para mandar una lectura manual.
9. Usa **Probar alerta crítica** para validar el flujo de emergencia.
10. Usa **Enviar reporte PDF** para mandar un informe con gráficas de la sesión.
