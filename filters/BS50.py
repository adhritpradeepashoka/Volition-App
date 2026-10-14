# Band-Stop Butterworth IIR digital filter
# Sampling rate: 500.0 Hz, frequency: [48.0, 52.0] Hz
# Filter is order 2, implemented as second-order sections (biquads)
# Reference: https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.butter.html

class BS50:
    def __init__(self):
        # Initialize state variables for each biquad section
        self.z1_0 = 0.0
        self.z2_0 = 0.0
        self.z1_1 = 0.0
        self.z2_1 = 0.0

    def process(self, input_sample):
        """Process a single sample through the filter"""
        output = input_sample

        # Biquad section 0
        x = output - (-1.56858163 * self.z1_0) - (0.96424138 * self.z2_0)
        output = 0.96508099 * x + -1.56202714 * self.z1_0 + 0.96508099 * self.z2_0
        self.z2_0 = self.z1_0
        self.z1_0 = x

        # Biquad section 1
        x = output - (-1.61100358 * self.z1_1) - (0.96592171 * self.z2_1)
        output = 1.00000000 * x + -1.61854514 * self.z1_1 + 1.00000000 * self.z2_1
        self.z2_1 = self.z1_1
        self.z1_1 = x

        return output

    def reset(self):
        """Reset filter state variables"""
        self.z1_0 = 0.0
        self.z2_0 = 0.0
        self.z1_1 = 0.0
        self.z2_1 = 0.0


# Example usage:
# Single channel:
# filter = BS50()
# filter.reset()
# filtered_output = filter.process(sample)
# 
# Multi-channel (3 channels):
# filters = [BS50() for _ in range(3)]  # One filter per channel
# filtered_1 = filters[0].process(raw1)
# filtered_2 = filters[1].process(raw2)
# filtered_3 = filters[2].process(raw3)
