# Low-Pass Butterworth IIR digital filter
# Sampling rate: 500.0 Hz, frequency: 45.0 Hz
# Filter is order 2, implemented as second-order sections (biquads)
# Reference: https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.butter.html

class LP45:
    def __init__(self):
        # Initialize state variables for each biquad section
        self.z1_0 = 0.0
        self.z2_0 = 0.0

    def process(self, input_sample):
        """Process a single sample through the filter"""
        output = input_sample

        # Biquad section 0
        x = output - (-1.22465158 * self.z1_0) - (0.45044543 * self.z2_0)
        output = 0.05644846 * x + 0.11289692 * self.z1_0 + 0.05644846 * self.z2_0
        self.z2_0 = self.z1_0
        self.z1_0 = x

        return output

    def reset(self):
        """Reset filter state variables"""
        self.z1_0 = 0.0
        self.z2_0 = 0.0


# Example usage:
# Single channel:
# filter = LP45()
# filter.reset()
# filtered_output = filter.process(sample)
# 
# Multi-channel (3 channels):
# filters = [LP45() for _ in range(3)]  # One filter per channel
# filtered_1 = filters[0].process(raw1)
# filtered_2 = filters[1].process(raw2)
# filtered_3 = filters[2].process(raw3)
