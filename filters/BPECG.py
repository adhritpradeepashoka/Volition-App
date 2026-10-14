# Band-Pass Butterworth IIR digital filter
# Sampling rate: 500.0 Hz, frequency: [0.5, 30.0] Hz
# Filter is order 4, implemented as second-order sections (biquads)
# Reference: https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.butter.html

class BPECG:
    def __init__(self):
        # Initialize state variables for each biquad section
        self.z1_0 = 0.0
        self.z2_0 = 0.0
        self.z1_1 = 0.0
        self.z2_1 = 0.0
        self.z1_2 = 0.0
        self.z2_2 = 0.0
        self.z1_3 = 0.0
        self.z2_3 = 0.0

    def process(self, input_sample):
        """Process a single sample through the filter"""
        output = input_sample

        # Biquad section 0
        x = output - (-1.40446316 * self.z1_0) - (0.50442472 * self.z2_0)
        output = 0.00075907 * x + 0.00151814 * self.z1_0 + 0.00075907 * self.z2_0
        self.z2_0 = self.z1_0
        self.z1_0 = x

        # Biquad section 1
        x = output - (-1.63753730 * self.z1_1) - (0.76004658 * self.z2_1)
        output = 1.00000000 * x + 2.00000000 * self.z1_1 + 1.00000000 * self.z2_1
        self.z2_1 = self.z1_1
        self.z1_1 = x

        # Biquad section 2
        x = output - (-1.98814441 * self.z1_2) - (0.98818597 * self.z2_2)
        output = 1.00000000 * x + -2.00000000 * self.z1_2 + 1.00000000 * self.z2_2
        self.z2_2 = self.z1_2
        self.z1_2 = x

        # Biquad section 3
        x = output - (-1.99527606 * self.z1_3) - (0.99531581 * self.z2_3)
        output = 1.00000000 * x + -2.00000000 * self.z1_3 + 1.00000000 * self.z2_3
        self.z2_3 = self.z1_3
        self.z1_3 = x

        return output

    def reset(self):
        """Reset filter state variables"""
        self.z1_0 = 0.0
        self.z2_0 = 0.0
        self.z1_1 = 0.0
        self.z2_1 = 0.0
        self.z1_2 = 0.0
        self.z2_2 = 0.0
        self.z1_3 = 0.0
        self.z2_3 = 0.0


# Example usage:
# Single channel:
# filter = BPECG()
# filter.reset()
# filtered_output = filter.process(sample)
# 
# Multi-channel (3 channels):
# filters = [BPECG() for _ in range(3)]  # One filter per channel
# filtered_1 = filters[0].process(raw1)
# filtered_2 = filters[1].process(raw2)
# filtered_3 = filters[2].process(raw3)
