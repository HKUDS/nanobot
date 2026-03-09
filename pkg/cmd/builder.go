package cmd

import (
	"context"
	"errors"
	"fmt"
	"os"
	"reflect"
	"regexp"
	"strconv"
	"strings"
	"unsafe"

	"github.com/spf13/cobra"
)

var (
	caseRegexp = regexp.MustCompile("([a-z])([A-Z])")
)

type PersistentPreRunnable interface {
	PersistentPre(cmd *cobra.Command, args []string) error
}

type PreRunnable interface {
	Pre(cmd *cobra.Command, args []string) error
}

type Runnable interface {
	Run(cmd *cobra.Command, args []string) error
}

type Customizer interface {
	Customize(cmd *cobra.Command)
}

type fieldInfo struct {
	FieldType  reflect.StructField
	FieldValue reflect.Value
}

func fields(obj any) []fieldInfo {
	ptrValue := reflect.ValueOf(obj)
	objValue := ptrValue.Elem()

	var result []fieldInfo

	numFields := objValue.NumField()
	for i := range numFields {
		fieldType := objValue.Type().Field(i)
		if fieldType.Anonymous {
			if fieldType.Type.Kind() == reflect.Struct {
				result = append(result, fields(objValue.Field(i).Addr().Interface())...)
			} else if fieldType.Type.Kind() == reflect.Ptr && fieldType.Type.Elem().Kind() == reflect.Struct {
				result = append(result, fields(objValue.Field(i).Interface())...)
			}
		} else if !fieldType.Anonymous {
			result = append(result, fieldInfo{
				FieldValue: objValue.Field(i),
				FieldType:  objValue.Type().Field(i),
			})
		}
	}

	return result
}

func Name(obj any) string {
	ptrValue := reflect.ValueOf(obj)
	objValue := ptrValue.Elem()
	commandName := strings.Replace(objValue.Type().Name(), "Command", "", 1)
	commandName, _ = name(commandName, "", "")
	return commandName
}

func MainCtx(ctx context.Context, cmd *cobra.Command) {
	if err := cmd.ExecuteContext(ctx); err != nil {
		if strings.EqualFold("interrupt", err.Error()) || errors.Is(err, context.Canceled) {
			os.Exit(1)
		}
		_, _ = fmt.Fprintf(os.Stderr, "%v\n", err)
		os.Exit(1)
	}
}

func Main(cmd *cobra.Command) {
	MainCtx(SetupSignalContext(), cmd)
}

// Command populates a cobra.Command object by extracting args from struct tags of the
// Runnable obj passed. The Run method is assigned to the RunE of the command.
// children should be either Runnable or *cobra.Command
func Command(obj Runnable, children ...any) *cobra.Command {
	if parentEnv, ok := obj.(interface {
		ParentEnv() string
	}); ok {
		return command(obj, parentEnv.ParentEnv(), children...)
	}
	return command(obj, "", children...)
}

func command(obj Runnable, parentEnv string, children ...any) *cobra.Command {
	var (
		envs       []func()
		arrays     = map[string]reflect.Value{}
		slices     = map[string]reflect.Value{}
		maps       = map[string]reflect.Value{}
		boolmaps   = map[string]reflect.Value{}
		quantities = map[string]reflect.Value{}
		optString  = map[string]reflect.Value{}
		optBool    = map[string]reflect.Value{}
		optInt     = map[string]reflect.Value{}
		ptrValue   = reflect.ValueOf(obj)
		objValue   = ptrValue.Elem()
	)

	var (
		c = cobra.Command{
			SilenceUsage:  true,
			SilenceErrors: true,
		}
	)

	if len(children) > 0 {
		switch v := children[0].(type) {
		case *cobra.Command:
			c = *v
			children = children[1:]
		case cobra.Command:
			c = v
			children = children[1:]
		}
	}

	if c.Use == "" {
		c.Use = Name(obj)
	}

	for _, info := range fields(obj) {
		fieldType := info.FieldType
		v := info.FieldValue

		if strings.ToUpper(fieldType.Name[0:1]) != fieldType.Name[0:1] {
			continue
		}

		name, alias := name(fieldType.Name, fieldType.Tag.Get("name"), fieldType.Tag.Get("short"))
		usage := fieldType.Tag.Get("usage")
		if usage == "-" {
			continue
		}
		env := strings.Split(fieldType.Tag.Get("env"), ",")
		defValue := fieldType.Tag.Get("default")
		if len(env) == 1 && env[0] == "" {
			env = []string{strings.ToUpper(strings.ReplaceAll(parentEnv+Name(obj)+"_"+name, "-", "_"))}
		}
		defInt, err := strconv.Atoi(defValue)
		if err != nil {
			defInt = 0
		}
		defFloat, err := strconv.ParseFloat(defValue, 32)
		if err != nil {
			defFloat = 0
		}

		if len(env) > 0 {
			usage += fmt.Sprintf(" ($%s)", strings.Join(env, ","))
		}

		usage = strings.TrimSpace(usage)

		flags := c.PersistentFlags()
		if fieldType.Tag.Get("local") == "true" {
			flags = c.Flags()
		}

		switch fieldType.Type.Kind() {
		case reflect.Int:
			flags.IntVarP((*int)(unsafe.Pointer(v.Addr().Pointer())), name, alias, defInt, usage)
		case reflect.Int64:
			flags.IntVarP((*int)(unsafe.Pointer(v.Addr().Pointer())), name, alias, defInt, usage)
		case reflect.String:
			flags.StringVarP((*string)(unsafe.Pointer(v.Addr().Pointer())), name, alias, defValue, usage)
		case reflect.Float64:
			flags.Float64VarP((*float64)(unsafe.Pointer(v.Addr().Pointer())), name, alias, defFloat, usage)
		case reflect.Slice:
			switch fieldType.Tag.Get("split") {
			case "false":
				arrays[name] = v
				flags.StringArrayP(name, alias, nil, usage)
			default:
				slices[name] = v
				flags.StringSliceP(name, alias, nil, usage)
			}
		case reflect.Map:
			switch fieldType.Tag.Get("boolmap") {
			case "true":
				boolmaps[name] = v
			default:
				maps[name] = v
			}
			flags.StringSliceP(name, alias, nil, usage)
		case reflect.Bool:
			flags.BoolVarP((*bool)(unsafe.Pointer(v.Addr().Pointer())), name, alias, defValue == "true", usage)
		case reflect.Pointer:
			switch fieldType.Type.Elem().Kind() {
			case reflect.Int:
				optInt[name] = v
				flags.IntP(name, alias, defInt, usage)
			case reflect.Int64:
				// In the case that a quantity tag is found and set to true, we want to create a string flag
				// for it that will get parsed into an *int64. See assignQuantities().
				if fieldType.Tag.Get("quantity") == "true" {
					quantities[name] = v
					flags.StringP(name, alias, defValue, usage)
				} else {
					flags.Int64P(name, alias, int64(defInt), usage)
				}
			case reflect.String:
				optString[name] = v
				flags.StringP(name, alias, defValue, usage)
			case reflect.Bool:
				optBool[name] = v
				flags.BoolP(name, alias, false, usage)
			}
		default:
			panic("Unknown kind on field " + fieldType.Name + " on " + objValue.Type().Name())
		}

		for _, env := range env {
			envs = append(envs, func() {
				v := os.Getenv(env)
				if v != "" {
					fv := flags.Lookup(name)
					if fv != nil && !fv.Changed {
						_ = flags.Set(name, v)
					}
				}
			})
		}

		if fieldType.Tag.Get("hidden") == "true" {
			if err := flags.MarkHidden(name); err != nil {
				panic(err)
			}
		}
	}

	if p, ok := obj.(PersistentPreRunnable); ok {
		c.PersistentPreRunE = p.PersistentPre
	}

	if p, ok := obj.(PreRunnable); ok {
		c.PreRunE = p.Pre
	}

	c.RunE = obj.Run
	c.PersistentPreRunE = bind(c.PersistentPreRunE, arrays, slices, maps, boolmaps, optInt, optBool, optString, quantities, envs)
	c.PreRunE = bind(c.PreRunE, arrays, slices, maps, boolmaps, optInt, optBool, optString, quantities, envs)
	c.RunE = bind(c.RunE, arrays, slices, maps, boolmaps, optInt, optBool, optString, quantities, envs)

	cust, ok := obj.(Customizer)
	if ok {
		cust.Customize(&c)
	}

	for _, children := range children {
		switch v := children.(type) {
		case Runnable:
			prefix := strings.ToUpper(strings.ReplaceAll(parentEnv+Name(obj)+"_", "-", "_"))
			c.AddCommand(command(v, prefix))
		case *cobra.Command:
			c.AddCommand(v)
		default:
			panic(fmt.Sprintf("unknown type, expected Runnable or *cobra.Command: %T", children))
		}
	}

	return &c
}

func assignOptBool(app *cobra.Command, maps map[string]reflect.Value) error {
	for k, v := range maps {
		k = contextKey(k)
		if !app.Flags().Lookup(k).Changed {
			continue
		}
		i, err := app.Flags().GetBool(k)
		if err != nil {
			return err
		}
		v.Set(reflect.ValueOf(&i))
	}
	return nil
}

func assignQuantities(app *cobra.Command, maps map[string]reflect.Value) error {
	for k := range maps {
		k = contextKey(k)

		i, err := app.Flags().GetString(k)
		if err != nil {
			return err
		}

		if i == "" {
			continue
		}

		//quantity, err := aml.ParseInt(i)
		//if err != nil {
		//	return err
		//}

		//v.Set(reflect.ValueOf(&quantity))
	}
	return nil
}

func assignOptString(app *cobra.Command, maps map[string]reflect.Value) error {
	for k, v := range maps {
		k = contextKey(k)
		if !app.Flags().Lookup(k).Changed {
			continue
		}
		i, err := app.Flags().GetString(k)
		if err != nil {
			return err
		}
		v.Set(reflect.ValueOf(&i))
	}
	return nil
}

func assignOptInt(app *cobra.Command, maps map[string]reflect.Value) error {
	for k, v := range maps {
		k = contextKey(k)
		if !app.Flags().Lookup(k).Changed {
			continue
		}
		i, err := app.Flags().GetInt(k)
		if err != nil {
			return err
		}
		v.Set(reflect.ValueOf(&i))
	}
	return nil
}

func assignMaps(app *cobra.Command, maps map[string]reflect.Value) error {
	for k, v := range maps {
		k = contextKey(k)
		s, err := app.Flags().GetStringSlice(k)
		if err != nil {
			return err
		}
		if s != nil {
			values := map[string]string{}
			for _, part := range s {
				parts := strings.SplitN(part, "=", 2)
				if len(parts) == 1 {
					values[parts[0]] = ""
				} else {
					values[parts[0]] = parts[1]
				}
			}
			v.Set(reflect.ValueOf(values))
		}
	}
	return nil
}

func assignBoolMaps(app *cobra.Command, maps map[string]reflect.Value) error {
	for k, v := range maps {
		k = contextKey(k)
		s, err := app.Flags().GetStringSlice(k)
		if err != nil {
			return err
		}
		if s != nil {
			values := map[string]bool{}
			for _, part := range s {
				parts := strings.SplitN(part, "=", 2)
				if len(parts) == 1 {
					values[parts[0]] = true
				} else {
					values[parts[0]], err = strconv.ParseBool(parts[1])
					if err != nil {
						return err
					}
				}
			}
			v.Set(reflect.ValueOf(values))
		}
	}
	return nil
}

func assignSlices(app *cobra.Command, slices map[string]reflect.Value) error {
	for k, v := range slices {
		k = contextKey(k)
		s, err := app.Flags().GetStringSlice(k)
		if err != nil {
			return err
		}
		a := app.Flags().Lookup(k)
		if a.Changed && len(s) == 0 {
			s = []string{""}
		}
		if s != nil {
			v.Set(reflect.ValueOf(s[:]))
		}
	}
	return nil
}

func assignArrays(app *cobra.Command, arrays map[string]reflect.Value) error {
	for k, v := range arrays {
		k = contextKey(k)
		s, err := app.Flags().GetStringArray(k)
		if err != nil {
			return err
		}
		a := app.Flags().Lookup(k)
		if a.Changed && len(s) == 0 {
			s = []string{""}
		}
		if s != nil {
			v.Set(reflect.ValueOf(s[:]))
		}
	}
	return nil
}

func contextKey(name string) string {
	parts := strings.Split(name, ",")
	return parts[len(parts)-1]
}

func name(name, setName, short string) (string, string) {
	if setName != "" {
		return setName, short
	}
	parts := strings.Split(name, "_")
	i := len(parts) - 1
	name = caseRegexp.ReplaceAllString(parts[i], "$1-$2")
	name = strings.ToLower(name)
	result := append([]string{name}, parts[0:i]...)
	for i := range result {
		result[i] = strings.ToLower(result[i])
	}
	if short == "" && len(result) > 1 {
		short = result[1]
	}
	return result[0], short
}

func bind(next func(*cobra.Command, []string) error,
	arrays map[string]reflect.Value,
	slices map[string]reflect.Value,
	maps map[string]reflect.Value,
	boolMaps map[string]reflect.Value,
	optInt map[string]reflect.Value,
	optBool map[string]reflect.Value,
	optString map[string]reflect.Value,
	quantites map[string]reflect.Value,
	envs []func()) func(*cobra.Command, []string) error {
	if next == nil {
		return nil
	}
	return func(cmd *cobra.Command, args []string) error {
		for _, envCallback := range envs {
			envCallback()
		}
		if err := assignArrays(cmd, arrays); err != nil {
			return err
		}
		if err := assignSlices(cmd, slices); err != nil {
			return err
		}
		if err := assignMaps(cmd, maps); err != nil {
			return err
		}
		if err := assignBoolMaps(cmd, boolMaps); err != nil {
			return err
		}
		if err := assignOptInt(cmd, optInt); err != nil {
			return err
		}
		if err := assignOptBool(cmd, optBool); err != nil {
			return err
		}
		if err := assignOptString(cmd, optString); err != nil {
			return err
		}
		if err := assignQuantities(cmd, quantites); err != nil {
			return err
		}

		if next != nil {
			return next(cmd, args)
		}

		return nil
	}
}
