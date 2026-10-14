# Volition: Adaptive Biosignal Platform for Universal Assistive Control

## Problem ( 450 chars )

As per Census 2011, 54 lakh Indians live with motor disabilities -
conservatively over 65 lakh today. Assistive devices like myoelectric
arms and smart wheelchairs cost ₹1- 8 lakh, require professional
calibration, and depend on internet connectivity. For 95% of Indian
families, these aren't just expensive; they're completely out of reach.
No affordable, offline, and self-calibrating easy-to-use solution
currently exists.

## Objectives ( 500 chars )

To develop an offline adaptive biosignal platform that reads EMG, EOG,
and EEG signals to map each user's neural signature (targeting \>80%
accuracy) through a one-time guided setup - without clinical calibration
or internet - and translate it into actionable commands for computers,
household appliances, and mobility aids via one universal application.
Ultimately, the objective is to make assistive technology accessible and
affordable to every affected Indian, regardless of income or location.

## Methods ( 500 chars )

The NPG Lite captures biopotential signals from skin-contact electrodes
and streams them wirelessly through Bluetooth(BLE) to the Volition
application. A lightweight machine learning pipeline processes these
streams in parallel to classify intents from different body parts. The
software’s architecture is engineered to map these classified intents
directly into digital control commands, routing them wirelessly to
connected devices and hardware interfaces.

## Scientific Approach ( 350 )

Volition fuses multi-modal biosignals with real-time sensing. EMG
(20-500Hz) tracks muscle twitches, EOG captures eye movement, and EEG
beta waves (12-30Hz) reflect cognitive intent. A background Passive
Floor Tracker auto-calibrates resting baselines, eliminating
single-channel false triggers for reliable assistive control.

## Results ( 400 )

Biopotentials are transmitted successfully over BLE and classified into
EMG, EOG, and EEG intents through self-calibrating thresholds requiring
only a brief guided setup, driving real-time computer control offline.
This is achieved using reusable, moisture-activated semidry electrodes
in place of disposable ones, keeping per-use costs negligible for
long-term, everyday use.

## Conclusions (400)

By offering a ₹4,000 - 8,500 alternative to ₹1-8 lakh commercial
assistive devices, Volition brings physical independence within reach of
India's 65 lakh+ motor-impaired citizens, with a modular, open-source
architecture designed for future expansion.

## Target Population(100)

Everyday Indians reclaiming their physical autonomy and dignity after
severe motor impairments.

## Social Impact(200)

After a one-time setup at any of India's 714 government district
hospitals, Volition runs entirely offline & self-calibrates at no cost,
restoring autonomy and easing caregiving burdens nationwide.

## Bibliography(200)

Census of India 2011, Disabled Persons in India, censusindia.gov.in

UDL NPG Lite Schematics, github.com/upsidedownlabs

TensorFlow Lite, tensorflow.org/lite

Health Dynamics of India 2022-23, MoHFW
