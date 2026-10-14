// Volition firmware — Copyright (c) 2026 Adhrit Pradeep. GPL-3.0.
// Based on the public NPG-LITE-BLE firmware architecture from Upside Down Labs.
/*
  NPG Lite BLE + Volition IMU firmware
  -------------------------------------

  Based on the public NPG-LITE-BLE firmware architecture from
  Upside Down Labs, with the existing ADC/BLE data format preserved.

  Volition additions:
    - MPU6050 / MPU6500 detection over I2C
    - NPG Lite ESP32-C6 I2C pins: SDA GPIO22, SCL GPIO23
    - Separate BLE IMU notification characteristic
    - 100 Hz six-axis IMU stream
    - Existing START / STOP commands control both ADC and IMU streams

  Existing BLE UUIDs are preserved:
    Service:  4fafc201-1fb5-459e-8fcc-c5c9c331914b
    Data:     beb5483e-36e1-4688-b7f5-ea07361b26a8
    Control:  0000ff01-0000-1000-8000-00805f9b34fb
    Battery:  f633d0ec-46b4-43c1-a39f-1ca06d0602e1

  New IMU UUID:
    8b5f4e5c-7d3a-4f91-ae2c-7e2f4c7f6a11

  IMU notification (16 bytes, little-endian):
    uint32_t timestamp_ms
    int16_t  ax
    int16_t  ay
    int16_t  az
    int16_t  gx
    int16_t  gy
    int16_t  gz

  Current IMU configuration:
    Accelerometer: +/-2 g  -> 16384 LSB/g
    Gyroscope:     +/-250 dps -> 131 LSB/(deg/s)
*/

#include <Arduino.h>
#include <math.h>
#include <Wire.h>

#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLE2902.h>
#include <BLEUtils.h>

#include <Adafruit_NeoPixel.h>
#include <sdkconfig.h>
#include "hal/efuse_hal.h"
#include "esp_idf_version.h"
#include "esp_mac.h"
#include "esp_sleep.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

// ADC includes
#include "esp_bt.h"
#include "esp_adc/adc_continuous.h"
#include "hal/adc_types.h"
#include "soc/soc_caps.h"

// ============================================================
// PLAYMATE / BOARD CONFIGURATION
// ============================================================

#define PROTO_PLAYMATE 0
#define VIBZ_PLAYMATE 1
#define VIBZ_PLUS_PLAYMATE 2

#if defined(CONFIG_IDF_TARGET_ESP32C6)
uint32_t chiprev = efuse_hal_chip_revision();
#define GAIN_PIN 14
#define LED_BUILTIN 7
#define BUZZER_PIN 8
#define PIXEL_PIN 15
#define PIXEL_COUNT 6
#elif defined(CONFIG_IDF_TARGET_ESP32C3)
#define LED_BUILTIN 6
#define BUZZER_PIN 8
#define PIXEL_PIN 3
#define PIXEL_COUNT 4
#else
#error "Unsupported board: target ESP32-C6 or ESP32-C3."
#endif

#define NUM_CHANNELS_MAX 7
#define BLE_PAYLOAD_BUFFERS 2
#define PIXEL_BRIGHTNESS 7
#define BLOCK_COUNT 10
#define SAMP_RATE 500.0
#define BATTERY_PIN A6
#define BOOT_MIN_BATTERY 10.0
#define STREAMING_MIN_BATTERY 5.0

static uint8_t NUM_CHANNELS = 4;
static uint8_t SINGLE_SAMPLE_LEN = 0;
static uint16_t NEW_PACKET_LEN = 0;
static uint8_t Playmate = PROTO_PLAYMATE;

static inline void recomputePacketSizes()
{
  SINGLE_SAMPLE_LEN = (uint8_t)(2 * (NUM_CHANNELS - 1) + 1);
  NEW_PACKET_LEN = (uint16_t)(BLOCK_COUNT * SINGLE_SAMPLE_LEN);
}

Adafruit_NeoPixel pixels(PIXEL_COUNT, PIXEL_PIN, NEO_GRB + NEO_KHZ800);

// ============================================================
// BATTERY
// ============================================================

static unsigned long lastBatteryCheck = 0;
static const unsigned long BATTERY_CHECK_INTERVAL = 10000;

const float voltageLUT[] = {
    3.27, 3.61, 3.69, 3.71, 3.73, 3.75, 3.77, 3.79, 3.80, 3.82,
    3.84, 3.85, 3.87, 3.91, 3.95, 3.98, 4.02, 4.08, 4.11, 4.15, 4.20};

const int percentLUT[] = {
    0, 5, 10, 15, 20, 25, 30, 35, 40, 45,
    50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100};

const int lutSize = sizeof(voltageLUT) / sizeof(voltageLUT[0]);

float interpolatePercentage(float voltage)
{
  if (voltage <= voltageLUT[0]) return 0;
  if (voltage >= voltageLUT[lutSize - 1]) return 100;

  int i = 0;
  while (i < lutSize - 1 && voltage > voltageLUT[i + 1]) i++;

  float v1 = voltageLUT[i], v2 = voltageLUT[i + 1];
  int p1 = percentLUT[i], p2 = percentLUT[i + 1];
  return p1 + (voltage - v1) * (p2 - p1) / (v2 - v1);
}

static volatile uint16_t latestBatteryRaw = 0;
static uint32_t batteryWinStartMs = 0;
static uint32_t batteryWinSum = 0;
static uint16_t batteryWinCount = 0;
static uint16_t batteryAvgToSend = 0;
static uint16_t isCharging = 0;
static uint8_t lastBatteryPct = 255;
static uint8_t consecutiveChargingCheck = 3;

// ============================================================
// BLE UUIDS
// ============================================================

#define SERVICE_UUID "4fafc201-1fb5-459e-8fcc-c5c9c331914b"
#define DATA_CHAR_UUID "beb5483e-36e1-4688-b7f5-ea07361b26a8"
#define CONTROL_CHAR_UUID "0000ff01-0000-1000-8000-00805f9b34fb"
#define BATTERY_CHAR_UUID "f633d0ec-46b4-43c1-a39f-1ca06d0602e1"
#define IMU_CHAR_UUID "8b5f4e5c-7d3a-4f91-ae2c-7e2f4c7f6a11"

// ============================================================
// GLOBAL BLE / STREAM STATE
// ============================================================

uint8_t blePayload[BLE_PAYLOAD_BUFFERS]
                 [BLOCK_COUNT * (2 * (NUM_CHANNELS_MAX - 1) + 1)] = {0};

static uint8_t payload_wr = 0;
static uint8_t payload_rd = 0;
static uint8_t payload_full = 0;
static uint8_t sampleIndex = 0;
volatile bool streaming = false;
uint8_t mac[6];

static volatile bool adc_start_requested = false;
static volatile bool adc_stop_requested = false;

BLEServer *pBLEServer = nullptr;
BLECharacteristic *pDataCharacteristic = nullptr;
BLECharacteristic *pControlCharacteristic = nullptr;
BLECharacteristic *pBatteryCharacteristic = nullptr;
BLECharacteristic *pIMUCharacteristic = nullptr;

uint8_t overallCounter = 0;

// ============================================================
// ADC DMA STATE
// ============================================================

static adc_continuous_handle_t adc_handle = nullptr;
static bool adc_started = false;
static SemaphoreHandle_t adc_data_semaphore = nullptr;

#define ADC_OUTPUT_TYPE ADC_DIGI_OUTPUT_FORMAT_TYPE2
#define ADC_GET_CHANNEL(p) ((p)->type2.channel)
#define ADC_GET_DATA(p) ((p)->type2.data)

static int8_t hw2idx[10];
static const uint8_t hw_chs_4[4] = {0, 1, 2, 6};
static const uint8_t hw_chs_7[7] = {0, 1, 2, 3, 4, 5, 6};
static uint16_t last_vals[NUM_CHANNELS_MAX] = {0};
static uint32_t have_mask = 0;

static inline void resetSampleState()
{
  have_mask = 0;
  for (uint8_t i = 0; i < NUM_CHANNELS_MAX; i++) last_vals[i] = 0;
}

// ============================================================
// IMU STATE / DRIVER
// ============================================================

#define IMU_SDA_PIN 22
#define IMU_SCL_PIN 23
#define IMU_SAMPLE_HZ 100
#define IMU_PERIOD_MS (1000 / IMU_SAMPLE_HZ)

static const uint8_t IMU_I2C_ADDRESSES[] = {0x68, 0x69};
static const uint8_t IMU_I2C_ADDRESS_COUNT =
    sizeof(IMU_I2C_ADDRESSES) / sizeof(IMU_I2C_ADDRESSES[0]);

#define MPU_REG_WHO_AM_I     0x75
#define MPU_REG_PWR_MGMT_1   0x6B
#define MPU_REG_SMPLRT_DIV   0x19
#define MPU_REG_CONFIG       0x1A
#define MPU_REG_GYRO_CONFIG  0x1B
#define MPU_REG_ACCEL_CONFIG 0x1C
#define MPU_REG_ACCEL_XOUT_H 0x3B

static uint8_t imuAddress = 0;
static uint8_t imuWhoAmI = 0;
static bool imuPresent = false;

struct __attribute__((packed)) IMUPacket
{
  uint32_t timestamp_ms;
  int16_t ax;
  int16_t ay;
  int16_t az;
  int16_t gx;
  int16_t gy;
  int16_t gz;
};

static bool imuWriteRegister(uint8_t reg, uint8_t value)
{
  Wire.beginTransmission(imuAddress);
  Wire.write(reg);
  Wire.write(value);
  return Wire.endTransmission() == 0;
}

static bool imuReadRegister(uint8_t reg, uint8_t &value)
{
  Wire.beginTransmission(imuAddress);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(imuAddress, (uint8_t)1) != 1) return false;
  value = Wire.read();
  return true;
}

static bool imuReadRegisters(uint8_t reg, uint8_t *buffer, uint8_t length)
{
  Wire.beginTransmission(imuAddress);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(imuAddress, length) != length) return false;
  for (uint8_t i = 0; i < length; i++) buffer[i] = Wire.read();
  return true;
}

static bool imuInitialize()
{
  for (uint8_t i = 0; i < IMU_I2C_ADDRESS_COUNT; i++)
  {
    imuAddress = IMU_I2C_ADDRESSES[i];

    uint8_t who = 0;
    if (!imuReadRegister(MPU_REG_WHO_AM_I, who)) continue;

    // MPU6050 = 0x68, MPU6500 = 0x70.
    if (who != 0x68 && who != 0x70) continue;

    imuWhoAmI = who;

    if (!imuWriteRegister(MPU_REG_PWR_MGMT_1, 0x00)) return false;
    delay(10);
    imuWriteRegister(MPU_REG_SMPLRT_DIV, 0x00);
    imuWriteRegister(MPU_REG_CONFIG, 0x00);
    imuWriteRegister(MPU_REG_GYRO_CONFIG, 0x00);  // +/-250 dps
    imuWriteRegister(MPU_REG_ACCEL_CONFIG, 0x00); // +/-2g
    delay(10);

    imuPresent = true;

    Serial.print("[Volition IMU] Found MPU at 0x");
    Serial.print(imuAddress, HEX);
    Serial.print(" WHO_AM_I=0x");
    Serial.println(imuWhoAmI, HEX);
    return true;
  }

  imuPresent = false;
  Serial.println("[Volition IMU] No compatible MPU detected; BLE/ADC will continue normally.");
  return false;
}

static bool imuReadRaw(int16_t &ax, int16_t &ay, int16_t &az,
                       int16_t &gx, int16_t &gy, int16_t &gz)
{
  uint8_t data[14];
  if (!imuReadRegisters(MPU_REG_ACCEL_XOUT_H, data, 14)) return false;

  ax = (int16_t)((data[0] << 8) | data[1]);
  ay = (int16_t)((data[2] << 8) | data[3]);
  az = (int16_t)((data[4] << 8) | data[5]);
  gx = (int16_t)((data[8] << 8) | data[9]);
  gy = (int16_t)((data[10] << 8) | data[11]);
  gz = (int16_t)((data[12] << 8) | data[13]);
  return true;
}

static void imuTask(void *parameter)
{
  TickType_t lastWake = xTaskGetTickCount();
  const TickType_t period = pdMS_TO_TICKS(IMU_PERIOD_MS);

  for (;;)
  {
    if (!streaming || !imuPresent || pIMUCharacteristic == nullptr ||
        pBLEServer == nullptr || pBLEServer->getConnectedCount() == 0)
    {
      vTaskDelay(pdMS_TO_TICKS(50));
      lastWake = xTaskGetTickCount();
      continue;
    }

    int16_t ax, ay, az, gx, gy, gz;
    if (imuReadRaw(ax, ay, az, gx, gy, gz))
    {
      IMUPacket packet;
      packet.timestamp_ms = millis();
      packet.ax = ax;
      packet.ay = ay;
      packet.az = az;
      packet.gx = gx;
      packet.gy = gy;
      packet.gz = gz;

      pIMUCharacteristic->setValue(
          reinterpret_cast<uint8_t *>(&packet), sizeof(packet));
      pIMUCharacteristic->notify();
    }

    vTaskDelayUntil(&lastWake, period);
  }
}

// ============================================================
// LED STATE
// ============================================================

static TaskHandle_t ledBlinkTask = NULL;
static volatile int ledBlinkCycles = -1;

void neoPixelTask(void *parameter)
{
  while (true)
  {
    if (ledBlinkCycles == -1)
    {
      vTaskDelay(100 / portTICK_PERIOD_MS);
      continue;
    }

    uint8_t cycles = 0;
    uint8_t fader = 100;
    bool decreasing = true;

    while (ledBlinkCycles != -1 &&
           (ledBlinkCycles == 0 || cycles < (uint8_t)ledBlinkCycles))
    {
      pixels.setPixelColor(PIXEL_COUNT - 1, pixels.Color(fader, 0, 0));
      pixels.show();
      vTaskDelay(20 / portTICK_PERIOD_MS);

      if (decreasing)
      {
        fader = (fader > 2) ? (fader - 2) : 0;
        if (fader < 10) decreasing = false;
      }
      else
      {
        fader += 2;
        if (fader > 100)
        {
          fader = 100;
          decreasing = true;
          cycles++;
        }
      }
    }

    if (ledBlinkCycles > 0)
    {
      pixels.clear();
      pixels.show();
      ledBlinkCycles = -1;
    }
  }
}

// ============================================================
// BATTERY FUNCTIONS
// ============================================================

void sleepWhenLowBattery()
{
  ledBlinkCycles = 10;
  while (ledBlinkCycles != -1) vTaskDelay(50 / portTICK_PERIOD_MS);
  esp_deep_sleep_start();
}

void checkInitialBattery()
{
  int count = 0;
  float sum = 0.0;
  unsigned long startMillis = millis();

  while (millis() - startMillis < 100)
  {
    sum += analogRead(BATTERY_PIN);
    count++;
  }

  if (count == 0) return;

  float initialBatteryRaw = sum / count;
  float voltage = (initialBatteryRaw / 1000.0) * 2;
  voltage -= 0.02;
  float percentage = ceil(interpolatePercentage(voltage));

  if (percentage < BOOT_MIN_BATTERY) sleepWhenLowBattery();
}

void checkBatteryAndDisconnect()
{
  if (batteryAvgToSend == 0 || pBatteryCharacteristic == nullptr) return;

  float voltage = (batteryAvgToSend / 1000.0) * 2;
  voltage -= 0.02;
  float percentage = ceil(interpolatePercentage(voltage));
  uint8_t currentBatteryPct = (uint8_t)percentage;

  if (lastBatteryPct == 255)
  {
    lastBatteryPct = currentBatteryPct;
    isCharging = 0;
  }
  else if (currentBatteryPct <= lastBatteryPct)
  {
    lastBatteryPct = currentBatteryPct;
    isCharging = 0;
  }
  else
  {
    if (isCharging >= consecutiveChargingCheck) lastBatteryPct = currentBatteryPct;
    isCharging++;
  }

  pBatteryCharacteristic->setValue(&lastBatteryPct, 1);
  pBatteryCharacteristic->notify();

  if (percentage > 70.0)
  {
    ledBlinkCycles = -1;
    pixels.setPixelColor(PIXEL_COUNT - 1, pixels.Color(0, PIXEL_BRIGHTNESS, 0));
    pixels.show();
  }
  else if (percentage > 20.0)
  {
    ledBlinkCycles = -1;
    pixels.setPixelColor(PIXEL_COUNT - 1, pixels.Color(15, 4, 0));
    pixels.show();
  }
  else if (percentage > 10.0)
  {
    ledBlinkCycles = -1;
    pixels.setPixelColor(PIXEL_COUNT - 1, pixels.Color(PIXEL_BRIGHTNESS, 0, 0));
    pixels.show();
  }
  else if (percentage >= STREAMING_MIN_BATTERY)
  {
    ledBlinkCycles = 0;
  }
  else
  {
    streaming = false;
    adc_stop_requested = true;
    if (pBLEServer != nullptr && pBLEServer->getConnectedCount() > 0)
    {
      // The connection will be dropped by deep sleep; no low-level GAP API is needed.
    }
    sleepWhenLowBattery();
  }
}

// ============================================================
// PLAYMATE DETECTION
// ============================================================

void checkPlaymate()
{
  pinMode(LED_BUILTIN, INPUT_PULLUP);
  pinMode(BUZZER_PIN, INPUT_PULLUP);

  if (digitalRead(LED_BUILTIN) == HIGH && digitalRead(BUZZER_PIN) == HIGH)
  {
    Playmate = PROTO_PLAYMATE;
  }
  else
  {
    Playmate = VIBZ_PLAYMATE;

    pinMode(A3, INPUT_PULLUP);
    pinMode(A4, INPUT_PULLUP);
    pinMode(A5, INPUT_PULLUP);

    unsigned long start = millis();
    while (millis() - start < 100)
    {
      if (digitalRead(A3) == LOW || digitalRead(A4) == LOW || digitalRead(A5) == LOW)
      {
        Playmate = VIBZ_PLUS_PLAYMATE;
        break;
      }
    }

    pinMode(A3, INPUT);
    pinMode(A4, INPUT);
    pinMode(A5, INPUT);
  }

  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, LOW);
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);

  NUM_CHANNELS = (Playmate == VIBZ_PLUS_PLAYMATE) ? 7 : 4;
  recomputePacketSizes();
}

// ============================================================
// BLE CALLBACKS
// ============================================================

class MyServerCallbacks : public BLEServerCallbacks
{
  void onConnect(BLEServer *pServer) override
  {
    pixels.setPixelColor(0, pixels.Color(0, PIXEL_BRIGHTNESS, 0));
    pixels.show();
    digitalWrite(LED_BUILTIN, HIGH);
    vTaskDelay(200 / portTICK_PERIOD_MS);
    digitalWrite(LED_BUILTIN, LOW);
  }

  void onDisconnect(BLEServer *pServer) override
  {
    pixels.setPixelColor(0, pixels.Color(PIXEL_BRIGHTNESS, 0, 0));
    pixels.show();

    streaming = false;
    sampleIndex = 0;
    payload_wr = 0;
    payload_rd = 0;
    payload_full = 0;
    resetSampleState();
    lastBatteryPct = 255;
    isCharging = 0;
    batteryAvgToSend = 0;
    batteryWinSum = 0;
    batteryWinCount = 0;
    ledBlinkCycles = -1;

    adc_stop_requested = true;
    BLEAdvertising *advertising = BLEDevice::getAdvertising();
    if (advertising != nullptr) advertising->start();
  }
};

class ControlCallback : public BLECharacteristicCallbacks
{
  void onWrite(BLECharacteristic *characteristic) override
  {
    String cmd = characteristic->getValue();
    cmd.trim();
    cmd.toUpperCase();

    if (cmd == "START")
    {
      pixels.setPixelColor(0, pixels.Color(0, 0, PIXEL_BRIGHTNESS));
      pixels.show();

      overallCounter = 0;
      sampleIndex = 0;
      payload_wr = 0;
      payload_rd = 0;
      payload_full = 0;
      resetSampleState();

      batteryWinStartMs = millis();
      batteryWinSum = 0;
      batteryWinCount = 0;
      batteryAvgToSend = 0;
      isCharging = 0;
      lastBatteryPct = 255;
      ledBlinkCycles = -1;

      streaming = true;
      adc_start_requested = true;
    }
    else if (cmd == "STOP")
    {
      pixels.setPixelColor(0, pixels.Color(0, PIXEL_BRIGHTNESS, 0));
      pixels.show();
      streaming = false;
      resetSampleState();
      adc_stop_requested = true;
    }
    else if (cmd == "WHORU")
    {
      characteristic->setValue("NPG-LITE");
      characteristic->notify();
    }
    else if (cmd == "STATUS")
    {
      characteristic->setValue(streaming ? "RUNNING" : "STOPPED");
      characteristic->notify();
    }
    else
    {
      characteristic->setValue("UNKNOWN COMMAND");
      characteristic->notify();
    }
  }
};

// ============================================================
// ADC DMA
// ============================================================

static inline uint16_t fix_raw_if_needed(uint16_t raw)
{
#if defined(CONFIG_IDF_TARGET_ESP32C6)
  if (chiprev == 1)
  {
    uint32_t v = (uint32_t)raw * 4095u / 3249u;
    if (v > 4095u) v = 4095u;
    return (uint16_t)v;
  }
#endif
  return raw;
}

static void adc_dma_init()
{
  static adc_digi_pattern_config_t pattern[NUM_CHANNELS_MAX];
  const uint8_t *hw_chs = (NUM_CHANNELS == 7) ? hw_chs_7 : hw_chs_4;

  for (int i = 0; i < NUM_CHANNELS; i++)
  {
    pattern[i].atten = ADC_ATTEN_DB_11;
    pattern[i].channel = hw_chs[i];
    pattern[i].unit = ADC_UNIT_1;
    pattern[i].bit_width = ADC_BITWIDTH_12;
  }

  for (int i = 0; i < (int)sizeof(hw2idx); i++) hw2idx[i] = -1;
  for (int i = 0; i < NUM_CHANNELS; i++) hw2idx[hw_chs[i]] = i;

  adc_continuous_handle_cfg_t handle_cfg = {
      .max_store_buf_size = NUM_CHANNELS * SOC_ADC_DIGI_RESULT_BYTES * BLOCK_COUNT * 5,
      .conv_frame_size = NUM_CHANNELS * SOC_ADC_DIGI_RESULT_BYTES * BLOCK_COUNT,
#if defined(ESP_IDF_VERSION) && (ESP_IDF_VERSION >= ESP_IDF_VERSION_VAL(5, 3, 0))
      .flags = {.flush_pool = 1},
#endif
  };

  if (adc_handle == nullptr)
  {
    ESP_ERROR_CHECK(adc_continuous_new_handle(&handle_cfg, &adc_handle));
  }

  adc_continuous_evt_cbs_t cbs = {
      .on_conv_done = [](adc_continuous_handle_t handle,
                         const adc_continuous_evt_data_t *edata,
                         void *user_data) -> bool
      {
        BaseType_t xHigherPriorityTaskWoken = pdFALSE;
        xSemaphoreGiveFromISR(adc_data_semaphore, &xHigherPriorityTaskWoken);
        return (xHigherPriorityTaskWoken == pdTRUE);
      },
  };

  ESP_ERROR_CHECK(adc_continuous_register_event_callbacks(adc_handle, &cbs, nullptr));

  adc_continuous_config_t dig_cfg = {
      .pattern_num = NUM_CHANNELS,
      .adc_pattern = pattern,
      .sample_freq_hz = (uint32_t)(SAMP_RATE * NUM_CHANNELS),
      .conv_mode = ADC_CONV_SINGLE_UNIT_1,
      .format = ADC_OUTPUT_TYPE,
  };

  ESP_ERROR_CHECK(adc_continuous_config(adc_handle, &dig_cfg));
}

static void adc_dma_start()
{
  if (adc_handle == nullptr) adc_dma_init();

  if (adc_handle && !adc_started)
  {
    ESP_ERROR_CHECK(adc_continuous_start(adc_handle));
    adc_started = true;
  }
}

static void adc_dma_stop()
{
  if (adc_handle && adc_started)
  {
    ESP_ERROR_CHECK(adc_continuous_stop(adc_handle));
    adc_started = false;
    ESP_ERROR_CHECK(adc_continuous_deinit(adc_handle));
    adc_handle = nullptr;
  }
}

static void handle_adc_dma_and_notify()
{
  const uint32_t FULL_MASK = (1u << NUM_CHANNELS) - 1;
  uint8_t dma_buf[NUM_CHANNELS_MAX * SOC_ADC_DIGI_RESULT_BYTES * BLOCK_COUNT];

  while (payload_full < BLE_PAYLOAD_BUFFERS)
  {
    uint32_t ret_len = 0;
    esp_err_t ret = adc_continuous_read(adc_handle, dma_buf, sizeof(dma_buf), &ret_len, 0);
    if (ret != ESP_OK || ret_len == 0) break;

    for (uint32_t i = 0;
         i + SOC_ADC_DIGI_RESULT_BYTES <= ret_len;
         i += SOC_ADC_DIGI_RESULT_BYTES)
    {
      auto *p = (const adc_digi_output_data_t *)&dma_buf[i];
      uint8_t ch_hw = ADC_GET_CHANNEL(p);
      uint16_t raw = ADC_GET_DATA(p);

      int8_t idx = (ch_hw < (uint8_t)sizeof(hw2idx)) ? hw2idx[ch_hw] : -1;
      if (idx >= 0 && idx < (int8_t)NUM_CHANNELS)
      {
        if (idx < (NUM_CHANNELS - 1))
          last_vals[idx] = fix_raw_if_needed(raw);
        else
          last_vals[idx] = raw;

        have_mask |= (1u << idx);

        if (idx == (NUM_CHANNELS - 1))
          latestBatteryRaw = last_vals[idx];
      }

      if (have_mask == FULL_MASK)
      {
        if (payload_full >= BLE_PAYLOAD_BUFFERS)
        {
          have_mask = 0;
          break;
        }

        uint16_t offset = sampleIndex * SINGLE_SAMPLE_LEN;
        blePayload[payload_wr][offset] = overallCounter;
        overallCounter = (overallCounter + 1) & 0xFF;

        for (uint8_t c = 0; c < NUM_CHANNELS - 1; c++)
        {
          uint16_t v = last_vals[c];
          blePayload[payload_wr][offset + 1 + c * 2] = (uint8_t)((v >> 8) & 0xFF);
          blePayload[payload_wr][offset + 1 + c * 2 + 1] = (uint8_t)(v & 0xFF);
        }

        sampleIndex++;

        if (sampleIndex >= BLOCK_COUNT)
        {
          sampleIndex = 0;

          if (NUM_CHANNELS > 0)
          {
            uint16_t batt = last_vals[NUM_CHANNELS - 1];
            batteryWinSum += batt;
            batteryWinCount++;
          }

          uint32_t nowMs = millis();
          if ((uint32_t)(nowMs - batteryWinStartMs) >= BATTERY_CHECK_INTERVAL)
          {
            if (batteryWinCount > 0)
              batteryAvgToSend = (uint16_t)(batteryWinSum / batteryWinCount);

            batteryWinStartMs = nowMs;
            batteryWinSum = 0;
            batteryWinCount = 0;
          }

          payload_full++;
          payload_wr = (payload_wr + 1) % BLE_PAYLOAD_BUFFERS;

          if (payload_full >= BLE_PAYLOAD_BUFFERS)
          {
            have_mask = 0;
            break;
          }
        }

        have_mask = 0;
      }
    }
  }

  while (payload_full > 0 && streaming)
  {
    pDataCharacteristic->setValue(blePayload[payload_rd], NEW_PACKET_LEN);
    pDataCharacteristic->notify();

    payload_rd = (payload_rd + 1) % BLE_PAYLOAD_BUFFERS;
    payload_full--;
  }
}

// ============================================================
// SETUP
// ============================================================

void setup()
{
  Serial.begin(115200);

  pixels.begin();
  xTaskCreatePinnedToCore(neoPixelTask, "NeoPixelTask", 2048,
                          NULL, 1, &ledBlinkTask, 0);

  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, LOW);

  setCpuFrequencyMhz(80);

  checkPlaymate();
  checkInitialBattery();

  pixels.setPixelColor(0, pixels.Color(PIXEL_BRIGHTNESS, 0, 0));
  pixels.show();

  adc_data_semaphore = xSemaphoreCreateBinary();
  if (adc_data_semaphore == nullptr)
  {
    while (1) delay(1000);
  }

  esp_read_mac(mac, ESP_MAC_EFUSE_FACTORY);

  // Release Classic BT memory because this firmware uses BLE only.
  esp_bt_controller_mem_release(ESP_BT_MODE_CLASSIC_BT);

  // ----- IMU -----
  Wire.begin(IMU_SDA_PIN, IMU_SCL_PIN);
  Wire.setClock(400000);
  delay(10);
  imuInitialize();

  // ----- BLE -----
  char deviceName[36];
  if (Playmate == VIBZ_PLUS_PLAYMATE)
    sprintf(deviceName, "NPG-Lite-6CH:%02X:%02X", mac[4], mac[5]);
  else
    sprintf(deviceName, "NPG-Lite-3CH:%02X:%02X", mac[4], mac[5]);

  BLEDevice::init(deviceName);
  BLEDevice::setMTU(500);

  pBLEServer = BLEDevice::createServer();
  pBLEServer->setCallbacks(new MyServerCallbacks());

  BLEService *pService = pBLEServer->createService(SERVICE_UUID);

  // Existing ADC characteristic — unchanged UUID and packet format.
  pDataCharacteristic = pService->createCharacteristic(
      DATA_CHAR_UUID, BLECharacteristic::PROPERTY_NOTIFY);
  pDataCharacteristic->addDescriptor(new BLE2902());

  // Existing control characteristic.
  pControlCharacteristic = pService->createCharacteristic(
      CONTROL_CHAR_UUID,
      BLECharacteristic::PROPERTY_READ |
      BLECharacteristic::PROPERTY_WRITE |
      BLECharacteristic::PROPERTY_NOTIFY);
  pControlCharacteristic->setCallbacks(new ControlCallback());

  // Existing battery characteristic.
  pBatteryCharacteristic = pService->createCharacteristic(
      BATTERY_CHAR_UUID,
      BLECharacteristic::PROPERTY_READ |
      BLECharacteristic::PROPERTY_NOTIFY);
  pBatteryCharacteristic->addDescriptor(new BLE2902());

  // NEW: separate IMU characteristic.
  pIMUCharacteristic = pService->createCharacteristic(
      IMU_CHAR_UUID, BLECharacteristic::PROPERTY_NOTIFY);
  pIMUCharacteristic->addDescriptor(new BLE2902());

  pService->start();

  // Use the Arduino BLE advertising API instead of direct esp_gap BLE calls.
  BLEAdvertising *advertising = BLEDevice::getAdvertising();
  advertising->addServiceUUID(SERVICE_UUID);
  advertising->setScanResponse(true);
  advertising->setMinPreferred(0x06);
  advertising->setMinPreferred(0x12);
  advertising->start();

  // IMU task runs independently from ADC DMA handling.
  xTaskCreate(imuTask, "IMUTask", 4096, nullptr, 1, nullptr);

  Serial.println();
  Serial.println("====================================");
  Serial.println("NPG Lite BLE + Volition IMU ready");
  Serial.print("IMU: ");
  Serial.println(imuPresent ? "CONNECTED" : "NOT PRESENT");
  Serial.print("IMU address: 0x");
  Serial.println(imuAddress, HEX);
  Serial.println("BLE service started.");
  Serial.println("====================================");
}

// ============================================================
// LOOP
// ============================================================

void loop()
{
  if (adc_stop_requested)
  {
    adc_dma_stop();
    adc_stop_requested = false;
  }

  if (adc_start_requested)
  {
    adc_dma_start();
    adc_start_requested = false;
  }

  if (streaming)
  {
    unsigned long currentMillis = millis();
    if (currentMillis - lastBatteryCheck >= BATTERY_CHECK_INTERVAL)
    {
      lastBatteryCheck = currentMillis;
      checkBatteryAndDisconnect();
    }

    if (xSemaphoreTake(adc_data_semaphore, portMAX_DELAY) == pdTRUE)
      handle_adc_dma_and_notify();
  }
  else
  {
    vTaskDelay(pdMS_TO_TICKS(100));
  }
}
