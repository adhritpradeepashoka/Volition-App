# High-Pass Butterworth IIR digital filter
# Sampling rate: 500.0 Hz, frequency: 70.0 Hz
# Filter is order 2, implemented as second-order sections (biquads)
# Reference: https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.butter.html

class HP70:
    def __init__(self):
        # Initialize state variables for each biquad section
        self.z1_0 = 0.0
        self.z2_0 = 0.0

    def process(self, input_sample):
        """Process a single sample through the filter"""
        output = input_sample

        # Biquad section 0
        x = output - (-0.82523238 * self.z1_0) - (0.29463653 * self.z2_0)
        output = 0.52996723 * x + -1.05993445 * self.z1_0 + 0.52996723 * self.z2_0
        self.z2_0 = self.z1_0
        self.z1_0 = x

        return output

    def reset(self):
        """Reset filter state variables"""
        self.z1_0 = 0.0
        self.z2_0 = 0.0


# Example usage:
# Single channel:
# filter = HP70()
# filter.reset()
# filtered_output = filter.process(sample)
# 
# Multi-channel (3 channels):
# filters = [HP70() for _ in range(3)]  # One filter per channel
# filtered_1 = filters[0].process(raw1)
# filtered_2 = filters[1].process(raw2)
# filtered_3 = filters[2].process(raw3)
