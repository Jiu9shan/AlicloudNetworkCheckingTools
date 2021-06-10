package main

import (
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"
)

var (
	tArgs   TcppingArgs
	logger  *log.Logger
	result  = &ResultBucket{}
	logfile *os.File
)

type ResultBucket struct {
	is_initialled bool
	ok_count      int64
	error_count   int64
	min_time      int64
	max_time      int64
	avg_time      int64
	dst_host      string
	dst_port      int
	count_time    int64
}

func (r *ResultBucket) Put(conn_time int64, status bool) {
	if status == false {
		r.error_count++
	} else {
		r.count_time += conn_time
		r.ok_count++
		if r.is_initialled == false {
			r.min_time = conn_time
			r.max_time = conn_time
			r.avg_time = conn_time
			r.is_initialled = true
		} else {
			if conn_time < r.min_time {
				r.min_time = conn_time
			}
			if conn_time > r.max_time {
				r.max_time = conn_time
			}
			r.avg_time = r.count_time / r.ok_count
		}
	}
}

func (r *ResultBucket) GetStatistics() string {
	return fmt.Sprintf(`--- %s:%d tcpping statistics ---
%d packets transmitted, %d connected, %.6f connection failed
min/avg/max = %d/%d/%d ms`,
		r.dst_host, r.dst_port,
		r.error_count+r.ok_count, r.ok_count, float64(r.error_count)*100/float64(r.error_count+r.ok_count),
		r.min_time, r.avg_time, r.max_time)

}

type TcppingArgs struct {
	srcHost       string
	srcPort       int
	srcRotatePort int
	interval      int64
	timeout       int64
	count         int
	rst           bool
	delayClose    int
	dstHost       string
	dstPort       int
	l             bool
}

func InitArgs() {
	tArgs = TcppingArgs{}
	flag.StringVar(&tArgs.srcHost, "H", "", "Set local IP")
	flag.IntVar(&tArgs.srcPort, "P", 0, "Set local port")
	flag.IntVar(&tArgs.srcRotatePort, "L", 0, "Set local port(rotate)")
	flag.Int64Var(&tArgs.interval, "i", 1000, "Set connection interval(Millisecond)")
	flag.Int64Var(&tArgs.timeout, "t", 5, "Set timeout(second)")
	flag.IntVar(&tArgs.count, "c", -1, "Stop after sending count packets")
	flag.BoolVar(&tArgs.l, "l", false, "\n是否开启日志")
	flag.BoolVar(&tArgs.rst, "R", false, "\nSending reset to close connection instead of FIN")
	flag.IntVar(&tArgs.delayClose, "D", 0, "Delay specified number of seconds before send FIN or RST")
	flag.StringVar(&tArgs.dstHost, "d", "", "Target host or IP")
	flag.IntVar(&tArgs.dstPort, "p", 0, "Target port")
	flag.Parse()
}

func InitLog() {
	writers := []io.Writer{os.Stdout}
	if tArgs.l {
		//创建日志文件
		f, err := os.OpenFile("tcpping.log", os.O_WRONLY|os.O_CREATE|os.O_APPEND, 0644)
		if err != nil {
			log.Fatal(err)
		}
		//完成后，延迟关闭
		// defer f.Close()
		// 设置日志输出到文件
		// 定义多个写入器
		writers = append(writers, f)
		logfile = f

	}
	// fmt.Println(writers)
	fileAndStdoutWriter := io.MultiWriter(writers...)
	// 创建新的log对象
	// log.Ldate|log.Ltime|log.Lshortfile
	logger = log.New(fileAndStdoutWriter, "", log.Ldate|log.Ltime)
	// 使用新的log对象，写入日志内容
	logger.Println("tcpping start")

}

func listenSignal() {
	sigs := make(chan os.Signal, 1)
	signal.Notify(sigs, syscall.SIGINT, syscall.SIGTERM)
	v := <-sigs
	logger.Println("exit tcpping ,sigs:", v)
	my_exit()
}

func judge_args() bool {
	// src_host and src_port(src_rotate_port) must be given at the same time
	/* bool(argument.src_host) ^ (bool(argument.src_port) or bool(argument.src_rotate_port))
	localhost    0  1024                     true   true     false    true
	localhost    1024 0                      true   true     false    true
	localhost    1024 1024                   true   true     false     true
	localhost    0  0                        true   false    true     false
	""   0  1024                             false   true    true     false
	""   1024 0                              false   true    true     false
	""   1024 1024                           false   true    true     false
	""   0 0                                 false   false   false    true */
	return (tArgs.srcHost != "") == (tArgs.srcPort != 0 || tArgs.srcRotatePort != 0)
}

func ConnTcp() (int64, int64, error, string) {
	// (t1, t2, t3, te, conn_time, close_time, err, local_addr) = (-1, -1, -1, -1, -1, -1, '', None)
	var (
		t1, t2, t3 int64
	)

	d := &net.Dialer{
		Timeout: time.Duration(tArgs.timeout) * time.Second,
		Control: func(network, address string, c syscall.RawConn) error {
			return c.Control(func(fd uintptr) {
				// logger.Println("set socket opts")
				if tArgs.rst {
					syscall.SetsockoptLinger(int(fd), syscall.SOL_SOCKET, syscall.SO_LINGER, &syscall.Linger{1, 0})
				}
				if tArgs.srcHost != "" && tArgs.srcPort != 0 && tArgs.srcPort < 65536 {
					syscall.SetsockoptInt(int(fd), syscall.SOL_SOCKET, syscall.SO_REUSEADDR, 1)
				}
			})
		},
	}
	if tArgs.srcHost != "" && tArgs.srcPort != 0 && tArgs.srcPort < 65536 {
		d.LocalAddr = &net.TCPAddr{
			IP:   net.ParseIP(tArgs.srcHost),
			Port: tArgs.srcPort,
		}
	}
	t1 = time.Now().UnixNano()
	conn, err := d.Dial("tcp", fmt.Sprintf("%s:%d", tArgs.dstHost, tArgs.dstPort))
	t2 = time.Now().UnixNano()
	if err != nil {
		fmt.Println("dial to ", tArgs.dstHost, ":", tArgs.dstPort, err.Error())
		return t2 - t1, -1, err, ""

	}
	local_addr := conn.LocalAddr().String()
	time.Sleep(time.Duration(tArgs.delayClose) * time.Second)
	conn.Close()
	t3 = time.Now().UnixNano()
	return t2 - t1, t3 - t2, nil, local_addr
	// d := net.Dialer{Timeout: time.Duration(tArgs.timeout) * time.Second, LocalAddr: }

}

func doJob() {
	if tArgs.srcRotatePort > 0 {
		tArgs.srcPort = tArgs.srcRotatePort
	}
	forFlag := true
	for forFlag {
		conn_time, _, err, local_addr := ConnTcp()
		result.Put(conn_time/1000000, err == nil)
		output := []string{}
		if local_addr != "" {
			output = append(output, local_addr)
		}
		output = append(output, fmt.Sprintf("%s:%d", tArgs.dstHost, tArgs.dstPort))
		if conn_time >= 0 {
			output = append(output, fmt.Sprintf("conn_time: %d ms", conn_time/1000000))
		}
		if err != nil {
			output = append(output, "ERROR: "+err.Error())
		}
		final_output := strings.Join(output, ",")
		logger.Println(final_output)

		if tArgs.srcRotatePort != 0 {
			tArgs.srcPort++
		}
		if tArgs.srcPort >= 65535 {
			logger.Println("Local port reach 65535,reset src port to 1024.")
			tArgs.srcPort = 1024
		}

		tArgs.count--
		if tArgs.count == 0 {
			forFlag = false
		}
		time.Sleep(time.Duration(tArgs.interval) * time.Millisecond)
	}

}

func my_exit() {
	rs := result.GetStatistics()
	logger.Println(rs)
	if logfile != nil {
		logfile.Close()
	}
	os.Exit(0)
}

func main() {
	InitArgs()
	InitLog()
	go listenSignal()
	// fmt.Println(tArgs)
	result.dst_host = tArgs.dstHost
	result.dst_port = tArgs.dstPort
	if judge_args() {
		doJob()
		logger.Println(result.GetStatistics())
	} else {
		logger.Println("src_host and src_port(src_rotate_port) must be given at the same time")
	}
	if logfile != nil {
		logfile.Close()
	}
}
