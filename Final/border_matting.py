import numpy as np
import cv2
import math

class BorderMatting:
    def __init__(self, img, trimap):
        self.img = img
        self.trimap = trimap                        # 0: background, 4: foreground
        self.w = 6                                  # for constructing new trimap
        self.lambda1 = 50                           # for smoothing regularizer
        self.lambda2 = 1000                         # for smoothing regularizer
        self.L = 20                                 # for sampling mean and sample variance (41-1)/2
        self.delta_level = 30                       # for minimizing energy function (DP)
        self.sigma_level = 10                       # for minimizing energy function (DP)
        self.C = []                                 # contour
        self.D = dict()                             # dictionary for t(n): format (xt, yt): [(x1, y1), ...]
        self.delta_sigma_dict = dict()              # dictionary for delta and sigma: format (xt, yt): (delta, sigma)

    def run(self):
        print("--start finding contour--")           # show progress
        self.find_contour()                         # find contour
        print("--start grouping pixels--")           # show progress
        self.pixel_group()                          # group pixels and map them to contour pixels
        print("--start minimizing energy--")         # show progress
        self.energy_function()                      # minimizing energy function: find delta and sigma pairs
        alpha_map = self.construct_alpha_map()      # use best delta and sigma pairs to construct alpha map
        return alpha_map


    ''' Main Utility Functions '''

    def find_contour(self):
        # TODO: use cv2 or hand-crafted one
        self.trimap = np.uint8(self.trimap)
        self.trimap = cv2.dilate(self.trimap, kernel=np.ones((3, 3), np.uint8), iterations=2)
        edges = cv2.Canny(self.trimap, threshold1=2, threshold2=3)

        # construct new trimap
        newmap = np.zeros_like(self.trimap)
        newmap[self.trimap == 0] = 0
        newmap[self.trimap == 4] = 4
        newmap[edges == 255] = 2
        self.trimap = newmap
        # print(self.trimap)

        visualize = np.zeros_like(self.img)
        visualize[self.trimap == 0] = [0, 0, 0]
        visualize[self.trimap == 4] = [255, 255, 255]
        visualize[self.trimap == 2] = [0, 0, 255]
        cv2.imwrite("visualize.png", visualize)

        # find contour
        indices = np.where(edges == 255)
        self.C = list(zip(indices[0], indices[1])) 
        # print(self.C)  
        return 
    
    def pixel_group(self):
        # find nearest contour pixel for each pixel in trimap
        for point in self.C:
            self.D[point] = []
        
        m, n = self.trimap.shape
        csize = len(self.C)
        # create DP map for each pixel
        dp = [[-1 for j in range(n)] for i in range(m)]
        for i in range(m):
            for j in range(n):
                min_dist = 100000000
                min_point = None
                flag = 0
                if i > 0 and j > 0 and dp[i - 1][j] != -1:
                    flag = 1
                    for p in range(max(dp[i-1][j]-2, 0), min(dp[i-1][j]+2, csize)):
                        dist = (i - self.C[p][0]) ** 2 + (j - self.C[p][1]) ** 2
                        if dist < min_dist:
                            min_dist = dist
                            min_point = self.C[p]
                if j > 0 and i > 0 and dp[i][j - 1] != -1:
                    flag = 1
                    for q in range(max(dp[i][j-1]-2, 0), min(dp[i][j-1]+2, csize)):
                        dist = (i - self.C[q][0]) ** 2 + (j - self.C[q][1]) ** 2
                        if dist < min_dist:
                            min_dist = dist
                            min_point = self.C[q]
                if flag == 0:
                    for point in self.C:
                        dist = (i - point[0]) ** 2 + (j - point[1]) ** 2
                        if dist < min_dist:
                            min_dist = dist
                            min_point = point
                dp[i][j] = self.C.index(min_point)
                if min_dist < self.w ** 2:
                    self.D[min_point].append((i, j))

        # for keys in self.D.keys():
        #     print(keys, self.D[keys])
        return
    

    def energy_function(self):
        ''' equation (12) in the paper '''
        # TODO: check errors
        # previous delta and sigma
        _delta = 1
        _sigma = 1

        for point in self.C:
            energy = 10000000000000
            best_delta = None
            best_sigma = None
            for delta in range(1, self.delta_level):
                for sigma in range(1, self.sigma_level):
                    delta = delta / self.delta_level * self.w
                    sigma = sigma / self.sigma_level * self.w
                    V = self.smoothing_regularizer(delta, _delta, sigma, _sigma)
                    D = 0
                    pixel_group = self.D[point]
                    for pixel in pixel_group:
                        distance = ((pixel[0] - point[0]) ** 2 + (pixel[1] - point[1]) ** 2) ** 0.5
                        if self.trimap[pixel[0]][pixel[1]] == 0:
                            distance = -distance
                        alpha = self.distance_to_alpha(distance, sigma, delta)
                        # print(alpha)
                        tmp = self.data_term(alpha, point)
                        D += tmp
                        # print(tmp)
                    if energy > V + D:
                        # print("energy: ", energy)
                        # print("V: ", V)
                        # print("D: ", D)
                        # print("delta: ", delta)
                        # print("sigma: ", sigma)
                        energy = V + D
                        best_delta = delta
                        best_sigma = sigma
            self.delta_sigma_dict[point] = (best_delta, best_sigma)
            _delta = best_delta
            _sigma = best_sigma

        # for keys in self.delta_sigma_dict.keys():
        #     print(keys, self.delta_sigma_dict[keys])
        return


    def construct_alpha_map(self):
        m, n = self.trimap.shape
        alpha_map = [[0 for j in range(n)] for i in range(m)]
        for i in range(m):
            for j in range(n):
                if self.trimap[i][j] == 0:
                    alpha_map[i][j] = 0
                elif self.trimap[i][j] == 4:
                    alpha_map[i][j] = 1
                else:
                    alpha_map[i][j] = -1
        for point in self.C:
            delta, sigma = self.delta_sigma_dict[point]
            pixel_group = self.D[point]
            for pixel in pixel_group:
                distance = ((pixel[0] - point[0]) ** 2 + (pixel[1] - point[1]) ** 2) ** 0.5
                if self.trimap[pixel[0]][pixel[1]] == 0:
                    distance = -distance
                alpha = self.distance_to_alpha(distance, sigma, delta)
                # print(alpha)
                alpha_map[pixel[0]][pixel[1]] = alpha
            distance = 0
            alpha = self.distance_to_alpha(distance, sigma, delta)
            alpha_map[point[0]][point[1]] = alpha
        # print(alpha_map)
        return alpha_map
    

    ''' Important equations in the paper '''

    def smoothing_regularizer(self, m1, v1, m2, v2):
        ''' equation (13) in the paper '''
        return self.lambda1 * (m1 - m2) ** 2 + self.lambda2 * (v1 - v2) ** 2


    def data_term(self, alpha, pos):
        ''' equation (14) in the paper '''
        # TODO: log2 or log10?
        return -1 * math.log(self.gaussian(alpha, self.alpha_mean(alpha, pos), self.alpha_variance(alpha, pos))) / math.log(2)
    

    def alpha_mean(self, alpha, pos):
        ''' equation (15) in the paper '''
        out = (1 - alpha) * self.sample_mean(pos, 0) + alpha * self.sample_mean(pos, 1)
        # print("alpha mean: ", out)
        return (1 - alpha) * self.sample_mean(pos, 0) + alpha * self.sample_mean(pos, 1)
    

    def alpha_variance(self, alpha, pos):
        ''' equation (15) in the paper '''
        return (1 - alpha) ** 2 * self.sample_variance(pos, 0) + alpha ** 2 * self.sample_variance(pos, 1)
    

    ''' Helper Functions '''

    def sample_mean(self, pos, alpha):
        area = self.img[pos[0] - self.L: pos[0] + self.L + 1, pos[1] - self.L: pos[1] + self.L + 1]
        trim = self.trimap[pos[0] - self.L: pos[0] + self.L + 1, pos[1] - self.L: pos[1] + self.L + 1]
        if alpha == 0:  # background
            mean = np.sum(area[trim == 0]) / self.L ** 2
        else:           # foreground
            mean = np.sum(area[trim == 4]) / self.L ** 2
        # print("sample mean: ", mean)
        return mean
    

    def sample_variance(self, pos, alpha):
        area = self.img[pos[0] - self.L: pos[0] + self.L + 1, pos[1] - self.L: pos[1] + self.L + 1]
        trim = self.trimap[pos[0] - self.L: pos[0] + self.L + 1, pos[1] - self.L: pos[1] + self.L + 1]
        if alpha == 0:  # background
            variance = np.sum((area[trim == 0] - self.sample_mean(pos, alpha)) ** 2) / self.L ** 2
        else:           # foreground
            variance = np.sum((area[trim == 4] - self.sample_mean(pos, alpha)) ** 2) / self.L ** 2
        # print("sample variance: ", variance)
        return variance
    

    def distance_to_alpha(self, distance, sigma, delta):
        if distance < 0:
            return 0
        return 1 / (1 + np.exp(-1 * (distance - delta) / sigma))
    

    def gaussian(self, x, mean, variance):
        out = np.exp(-(x - mean) ** 2 / (2 * variance)) / np.sqrt(2 * np.pi * variance)
        # print(out)
        return np.exp(-(x - mean) ** 2 / (2 * variance)) / np.sqrt(2 * np.pi * variance)

